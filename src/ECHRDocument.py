import os
import re
import json
from bs4 import BeautifulSoup
import PyPDF2
from wikidata_query import get_country_identifier
from regexp import strasbourg_case_law_re
from rdflib import Graph, URIRef, Literal, BNode, Namespace
from rdflib.namespace import RDF, XSD, DCTERMS, FOAF
from utils.extract_url import extract_document_url


class ECHRDocument:
    """
   IT: Classe che rappresenta una pronuncia della Corte Europea dei Diritti dell'Uomo

   EN: Class that represents a ruling of the European Court of Human Rights.
    """

    def __init__(self, html_path: str = None, pdf_path: str = None, file_name: str = None):
        """
        :param html_path: percorso in cui si trova il file html che contiene il documento
        :param pdf_path: percorso in cui si trova il file pdf che contiene il documento
        :param file_name: nome del file SENZA ESTENSIONE

        EN: 
        :param html_path: path where the HTML file containing the document is located  
        :param pdf_path: path where the PDF file containing the document is located  
        :param file_name: name of the file WITHOUT EXTENSION  

        """
        if html_path is not None and file_name is not None:
            path = html_path + "/" + file_name + ".html"
            if not os.path.exists(path):
                raise Exception(f"PATH ERROR (HTML): {os.path.abspath(path)} does not exist")
        if pdf_path is not None and file_name is not None:
            path = pdf_path + "/" + file_name + ".pdf"
            if not os.path.exists(path):
                raise Exception(f"PATH ERROR (PDF): {os.path.abspath(path)} does not exist")
        self._html_path = html_path
        self._pdf_path = pdf_path
        self._file_name = file_name
        self._case_detail = None
        self._body = None
        self._footnotes = None
        self._titles = []
        self._graph = Graph()

    def __str__(self):
        if self._file_name is None:
            return "Not initialized"
        return self._file_name

    def set_html_path(self, html_path: str) -> None:
        if html_path is not None and self._file_name is not None:
            path = html_path + "/" + self._file_name + ".html"
            if not os.path.exists(path):
                raise Exception(f"PATH ERROR (HTML): {os.path.abspath(path)} does not exist")
        self._html_path = html_path

    def get_html_path(self) -> str:
        return self._html_path

    def set_pdf_path(self, pdf_path: str) -> None:
        if pdf_path is not None and self._file_name is not None:
            path = pdf_path + "/" + self._file_name + ".pdf"
            if not os.path.exists(path):
                raise Exception(f"PATH ERROR (PDF): {os.path.abspath(path)} does not exist")
        self._pdf_path = pdf_path

    def get_pdf_path(self) -> str:
        return self._pdf_path

    def set_file_name(self, file_name: str) -> None:
        if (self._pdf_path is not None or self._html_path is not None) and self._file_name is not None:
            if self._pdf_path is not None:
                path = self._pdf_path + "/" + file_name + ".pdf"
            else:
                path = self._html_path + "/" + file_name + ".html"
            if not os.path.exists(path):
                raise Exception(f"PATH ERROR: {os.path.abspath(path)} does not exist")
        self._file_name = file_name

    def get_file_name(self) -> str:
        return self._file_name

    def _check_conclusions(self):
        conclusions = self._case_detail["Conclusion(s)"]
        if isinstance(conclusions, list):
            new_element = ""
            opened_parenthesis = 0
            closed_parenthesis = 0
            new_conclusions = []
            mod = False
            for element in conclusions:
                # print(opened_parenthesis, closed_parenthesis)
                # print("***********", element)
                for char in element:
                    if char == "(":
                        opened_parenthesis += 1
                    elif char == ")":
                        closed_parenthesis += 1
                # print("***********", opened_parenthesis, closed_parenthesis)
                if opened_parenthesis > closed_parenthesis:
                    new_element += element + " "
                    mod = True
                    # print("+++++++++++", new_element)
                elif opened_parenthesis == closed_parenthesis:
                    opened_parenthesis = 0
                    closed_parenthesis = 0
                    if mod:
                        new_element += element
                        # print("APPENDING", new_element)
                        new_conclusions.append(new_element)
                        mod = False
                        new_element = ""
                    else:
                        # print("APPENDING", element)
                        new_conclusions.append(element)
                else:
                    new_element += element + " "
            self._case_detail["Conclusion(s)"] = new_conclusions

        elif isinstance(conclusions, str):
            self._case_detail["Conclusion(s)"] = conclusions

    def extract_case_detail_from_html(self):
        """
        Estrae il contenuto della tab "Case Details" di un caso dal sito hudoc.echr.coe.int
        Ad esempio da https://hudoc.echr.coe.int/eng#{%22itemid%22:[%22001-58371%22]} si ottiene il seguente dizionario:
            Originating Body: Court (Grand Chamber)
            Document Type: Judgment (Merits and Just Satisfaction)
            Published in: Reports 1997-VI
            Title: CASE OF AYDIN v. TURKEY
            App. No(s).: 23178/94
            Importance Level: 1
            Represented by: N/A
            Respondent State(s): Türkiye
            Reference Date: 15/04/1996
            Judgment Date: 25/09/1997
            Conclusion(s): ['Preliminary objection rejected (estoppel)', 'Violation of Art. 3', 'Violation of Art. 13',
                'Not necessary to examine Art. 6-1', 'No violation of Art. 25-1',
                'Not necessary to examine Art. 28-1-a', 'Not necessary to examine Art. 53',
                'Pecuniary damage - claim dismissed', 'Non-pecuniary damage - financial award',
                'Costs and expenses partial award - Convention proceedings']
            Article(s): ['3', '6', '6-1', '13', '25', '25-1', '28', '28-1-a', '46', '46-1', '41', '34', '53']
            Separate Opinion(s): Yes
            Domestic Law: ['Criminal Code, Articles 179, 181, 191, 243, 245 and 416 ', 'Code of Criminal Procedure,
                Articles 153, 154, 163 and 165 ', 'Constitution, Article 125 ', 'Military Criminal Code, Article 152 ',
                'Civil Code, Articles 41, 46 and 47 ', 'Decree no. 285 modifying the application of Law no. 3713,
                the Anti-Terror Law (1981) ', 'Law no. 2935 of 25 October 1983 on the state of emergency, section 1']
            Strasbourg Case-Law: ['Ireland v. the United Kingdom judgment of 18 January 1978, Series A no. 25,
                pp. 64-65, §§ 160-161, p. 66, § 167', 'The Holy Monasteries v. Greece judgment of 9 December 1994,
                Series A no. 301-A, pp. 36-37, § 80',
                'Loizidou v. Turkey judgment of 23 March 1995 (preliminary objections),
                Series A no. 310, p. 19, § 44', 'Akdivar and Others v. Turkey judgment of 16 September 1996,
                Reports of Judgments and Decisions ("Reports") 1996-IV, p. 1219, § 105',
                'Aksoy v. Turkey judgment of 18 December 1996,
                Reports 1996-VI, p. 2272, § 38, p. 2278, § 62, p. 2285, § 92, p. 2286, § 95, p. 2287, § 98']
            International Law: United Nations Convention against Torture and Other Cruel,
                Inhuman or Degrading Treatment or Punishment of 10 December 1984, Articles 11, 12 and 13
            Keywords: ['(Art. 3) Prohibition of torture', '(Art. 3) Torture', '(Art. 13) Right to an effective remedy',
                '(Art. 13) Effective remedy', '(Art. 34) Individual applications', '(Art. 34) Individual',
                '(Art. 34) Hinder the exercise of the right of application', '(Art. 6) Right to a fair trial',
                '(Art. 46) Binding force and execution of judgments', '(Art. 41) Just satisfaction-{general}',
                '(Art. 53) Rights otherwise guaranteed']
            ECLI: ECLI:CE:ECHR:1997:0925JUD002317894

            I valori possono essere stringhe o liste di stringhe a seconda dei casi
        :return:
        """

        if self._html_path is None or self._file_name is None:
            return
        try:
            html = open(self._html_path + "/" + self._file_name + ".html", "r", encoding="UTF-8").read()
        except Exception as e:
            print(f"\033[1;31m{e}\033[0m")
            return
        soup = BeautifulSoup(html, 'html.parser')
        """
        div id="notice" contenente sezione dei case detail
        div class="row noticefield" contenente la riga
        div class="span2 noticefieldheading" contenente il nome del campo
        div class="col-offset-2 noticefieldvalue" contiene il valore del campo

        EN: 
        div id="notice" containing the case detail section
        div class="row noticefield" containing the row
        div class="span2 noticefieldheading" containing the field name
        div class="col-offset-2 noticefieldvalue" containing the field value
        """
        heading_list = soup.find_all("div", {"class": "span2 noticefieldheading"})
        value_list = soup.find_all("div", {"class": "col-offset-2 noticefieldvalue"})

        case_detail = {}
        for i in range(len(heading_list)):
            key = heading_list[i].text
            values = re.split(r'\t+\s*', value_list[i].text.strip().replace("more…", ""))
            if key == "App. No(s).":
                values = re.split(r'\s+', values[0])
            elif key == "Strasbourg Case-Law" and "\n" in values[0]:
                values = re.split(r'\n+', values[0])
            if len(values) == 1:
                case_detail[key] = values[0]
            else:
                case_detail[key] = values
        self._case_detail = case_detail
        self._check_conclusions()

    def get_case_detail(self) -> dict:
        return self._case_detail

    def case_detail_to_json(self, path: str):
        """
        :param path: percorso in cui salvare il file json
        :return:
        """
        if self._case_detail is None:
            return
        name = self._file_name + ".json"
        try:
            with open(path + "/" + name, "w", encoding="UTF-8") as f:
                json.dump(self._case_detail, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"\033[1;31m{e}\033[0m")

    def extract_body_from_html(self):
        """
        estrae il corpo del documento e le eventuali note a piè di pagina di una pagina dal sito hudoc.echr.coe.int
        :return:
        """
        if self._html_path is None or self._file_name is None:
            return
        try:
            html = open(self._html_path + "/" + self._file_name + ".html", "r", encoding="UTF-8").read()
        except Exception as e:
            print(f"\033[1;31m{e}\033[0m")
            return
        soup = BeautifulSoup(html, 'html.parser')
        """
        div id="document" contiene il testo del documento
        div id="_ftn[i]" contiene la nota a piè di pagina
        """
        document_text = soup.find("div", {"id": "document"}).text
        footnote_list = soup.find_all("div", {"id": re.compile(r"_ftn\d+")})
        footnote_text = ""
        if len(footnote_list) != 0:
            for footnote in footnote_list:
                document_text = document_text.replace(footnote.text, "")
                footnote_text += footnote.text + "\n"
            self._footnotes = footnote_text
        self._body = document_text

    def get_body(self) -> str:
        return self._body

    def get_footnotes(self) -> str:
        return self._footnotes

    def body_to_txt(self, path: str):
        """
        :param path: percorso in cui salvare il file txt
        :param path:
        :return:
        """
        if self._body is None:
            return
        try:
            with open(path + "/" + self._file_name + ".txt", "w", encoding="UTF-8") as f:
                f.write(self._body)
        except Exception as e:
            print(f"\033[1;31m{e}\033[0m")

    def footnotes_to_txt(self, path: str):
        """
        :param path: percorso in cui salvare il file txt
        :param path:
        :return:
        """
        if self._footnotes is None:
            return
        try:
            with open(path + "/" + self._file_name + ".txt", "w", encoding="UTF-8") as f:
                f.write(self._footnotes)
        except Exception as e:
            print(f"\033[1;31m{e}\033[0m")

    def extract_titles(self):
        # TODO se torna utile, migliorare implementazione
        if self._pdf_path is None or self._file_name is None:
            return
        path = self._pdf_path + "/" + self._file_name + ".pdf"
        try:
            titles = []
            pdf_file = open(path, 'rb')
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            for page in pdf_reader.pages:
                text = page.extract_text()
                # i titoli delle sezioni principali sono in maiuscolo
                for sentence in text.split('\n'):
                    if sentence.isupper():
                        titles.append(sentence)
            self._titles = titles
        except Exception as e:
            print(f"\033[1;31m{e}\033[0m")

    def get_titles(self) -> list:
        return self._titles

    def extract_triples_from_case_detail(self):
        if self._case_detail is None:
            return
        wd = Namespace("http://www.wikidata.org/entity/")
        custom_ns = Namespace("https://github.com/PeppeRubini/EVA-KG/tree/main/ontology/ontology.owl#")

        url = URIRef(extract_document_url(self._case_detail["Title"]))

        self._graph.add((url, DCTERMS.accessRights, Literal("public", datatype=XSD.string)))
        self._graph.add((url, DCTERMS.publisher, URIRef(wd.Q122880)))
        self._graph.add((url, DCTERMS.language, Literal("en", datatype=XSD.string)))
        self._graph.add((url, DCTERMS.coverage, URIRef(wd.Q6602)))

        keys = self._case_detail.keys()
        uri_list = []

        if "App. No(s)." in keys:
            for value in self._case_detail["App. No(s)."]:
                if isinstance(self._case_detail["App. No(s)."], str):
                    value = self._case_detail["App. No(s)."]
                uri = URIRef(custom_ns + value)
                uri_list.append(uri)
                self._graph.add(
                    (uri, URIRef(custom_ns + "hasApplicationNumber"), Literal(value, datatype=XSD.string)))
                if isinstance(self._case_detail["App. No(s)."], str):
                    break

        if "Title" in keys:
            self._graph.add((url, DCTERMS.title, Literal(self._case_detail["Title"], datatype=XSD.string)))

        if "Keywords" in keys:
            for value in self._case_detail["Keywords"]:
                if isinstance(self._case_detail["Keywords"], str):
                    value = self._case_detail["Keywords"]
                self._graph.add((url, DCTERMS.description, Literal(value, datatype=XSD.string)))
                if isinstance(self._case_detail["Keywords"], str):
                    break

        for uri in uri_list:
            if url is not None:
                self._graph.add((uri, DCTERMS.identifier, url))

            if "Originating Body" in keys:
                self._graph.add(
                    (uri, DCTERMS.creator, Literal(self._case_detail["Originating Body"], datatype=XSD.string)))

            if "Document Type" in keys:
                if self._case_detail["Document Type"] == "Judgment (Merits and Just Satisfaction)":
                    self._graph.add((uri, DCTERMS.type, URIRef(wd.Q3769186)))
                elif self._case_detail["Document Type"] == "Decision":
                    self._graph.add((uri, DCTERMS.type, URIRef(wd.Q327000)))

            if "Published in" in keys:
                self._graph.add(
                    (uri, DCTERMS.isPartOf, Literal(self._case_detail["Published in"], datatype=XSD.string)))

            if "Importance Level" in keys:
                if self._case_detail["Importance Level"] == "Key cases":
                    self._graph.add(
                        (uri, URIRef(custom_ns + "importanceLevel"), Literal(4, datatype=XSD.integer)))
                else:
                    self._graph.add(
                        (uri, URIRef(custom_ns + "importanceLevel"),
                         Literal(int(self._case_detail["Importance Level"]),
                                 datatype=XSD.integer)))

            if "Respondent State(s)" in keys:
                for value in self._case_detail["Respondent State(s)"]:
                    if isinstance(self._case_detail["Respondent State(s)"], str):
                        value = self._case_detail["Respondent State(s)"]
                    country = get_country_identifier(value)
                    self._graph.add((uri, URIRef(custom_ns + "respondentState"), URIRef(country)))
                    if isinstance(self._case_detail["Respondent State(s)"], str):
                        break

            if "Judgment Date" in keys:
                new_date = self._case_detail["Judgment Date"].split("/")
                new_date = new_date[2] + "-" + new_date[1] + "-" + new_date[0]
                self._graph.add((uri, DCTERMS.date, Literal(new_date, datatype=XSD.date)))

            if "Decision Date" in keys:
                new_date = self._case_detail["Decision Date"].split("/")
                new_date = new_date[2] + "-" + new_date[1] + "-" + new_date[0]
                self._graph.add((uri, DCTERMS.date, Literal(new_date, datatype=XSD.date)))

            if "ECLI" in keys:
                self._graph.add((uri, DCTERMS.isVersionOf, Literal(self._case_detail["ECLI"], datatype=XSD.string)))

            if "Represented by" in keys:
                for value in self._case_detail["Represented by"]:
                    if isinstance(self._case_detail["Represented by"], str):
                        value = self._case_detail["Represented by"]
                    if value != "N/A":
                        lawyer = BNode()
                        self._graph.add((uri, DCTERMS.contributor, lawyer))
                        self._graph.add((lawyer, FOAF.name, Literal(value, datatype=XSD.string)))
                        self._graph.add((lawyer, RDF.type, URIRef(wd.Q40348)))
                    if isinstance(self._case_detail["Represented by"], str):
                        break

            if "Article(s)" in keys:
                for value in self._case_detail["Article(s)"]:
                    if isinstance(self._case_detail["Article(s)"], str):
                        value = self._case_detail["Article(s)"]
                    self._graph.add((uri, URIRef(custom_ns + "involveConventionArticle"), Literal(value, datatype=XSD.string)))
                    if isinstance(self._case_detail["Article(s)"], str):
                        break

            if "Separate Opinion(s)" in keys:
                if self._case_detail["Separate Opinion(s)"] == "Yes":
                    self._graph.add((uri, URIRef(custom_ns + "unanimousDecision"), Literal(False, datatype=XSD.boolean)))
                else:
                    self._graph.add((uri, URIRef(custom_ns + "unanimousDecision"), Literal(True, datatype=XSD.boolean)))

            if "Conclusion(s)" in keys:
                for value in self._case_detail["Conclusion(s)"]:
                    if isinstance(self._case_detail["Conclusion(s)"], str):
                        value = self._case_detail["Conclusion(s)"]
                    self._graph.add((uri, DCTERMS.abstract, Literal(value, datatype=XSD.string)))
                    if isinstance(self._case_detail["Conclusion(s)"], str):
                        break

            if "Domestic Law" in keys:
                for value in self._case_detail["Domestic Law"]:
                    if isinstance(self._case_detail["Domestic Law"], str):
                        value = self._case_detail["Domestic Law"]
                    dl = BNode()
                    self._graph.add((uri, DCTERMS.references, dl))
                    self._graph.add((dl, DCTERMS.description, Literal(value, datatype=XSD.string)))
                    self._graph.add((dl, RDF.type, URIRef(custom_ns + "DomesticLaw")))
                    if isinstance(self._case_detail["Domestic Law"], str):
                        break

            if "Strasbourg Case-Law" in keys:
                for value in self._case_detail["Strasbourg Case-Law"]:
                    if isinstance(self._case_detail["Strasbourg Case-Law"], str):
                        value = self._case_detail["Strasbourg Case-Law"]
                    content = strasbourg_case_law_re(value)
                    scl = BNode()
                    self._graph.add((uri, DCTERMS.references, scl))
                    self._graph.add((scl, DCTERMS.description, Literal(value, datatype=XSD.string)))
                    self._graph.add((scl, RDF.type, URIRef(custom_ns + "StrasbourgCaseLaw")))
                    if content[0]:
                        self._graph.add((scl, DCTERMS.title, Literal(content[0], datatype=XSD.string)))
                    if content[1]:
                        self._graph.add(
                            (scl, URIRef(custom_ns + "hasApplicationNumber"),
                             Literal(content[1], datatype=XSD.string)))
                    if content[2]:
                        self._graph.add((scl, DCTERMS.date, Literal(content[2], datatype=XSD.date)))
                    if isinstance(self._case_detail["Strasbourg Case-Law"], str):
                        break

            if "International Law" in keys:
                for value in self._case_detail["International Law"]:
                    if isinstance(self._case_detail["International Law"], str):
                        value = self._case_detail["International Law"]
                    il = BNode()
                    self._graph.add((uri, DCTERMS.references, il))
                    self._graph.add((il, DCTERMS.description, Literal(value, datatype=XSD.string)))
                    self._graph.add((il, RDF.type, URIRef(custom_ns + "InternationalLaw")))
                    if isinstance(self._case_detail["International Law"], str):
                        break

    def extract_triples_from_body(self):
        # TODO implementare
        if self._body is None:
            return
        pass

    def get_triples(self) -> str:
        return self._graph.serialize()

    def get_graph(self) -> Graph:
        return self._graph

    def save_triples(self, path: str):
        if self._graph is None:
            return
        name = self._file_name + ".ttl"
        try:
            self._graph.serialize(destination=path + "/" + name, format="turtle")
        except Exception as e:
            print(f"\033[1;31m{e}\033[0m")


if __name__ == "__main__":
    """
    prova di utilizzo della classe
    """
    import pprint

    html_p = "../data/corpus_html"
    pdf_p = "../data/corpus_pdf"
    f_name = "CASE OF BARSOVA v. RUSSIA"
    json_path = "../data/case_detail_json"
    body_path = "../data/document_body"
    echr_document = ECHRDocument(html_path=html_p, pdf_path=pdf_p, file_name=f_name)
    print("DOCUMENT___________________________________________________________________________________________________")
    print(echr_document)
    echr_document.extract_case_detail_from_html()
    print("CASE DETAIL________________________________________________________________________________________________")
    pprint.pprint(echr_document.get_case_detail(), sort_dicts=False)
    echr_document.case_detail_to_json(json_path)
    echr_document.extract_body_from_html()
    print("BODY_______________________________________________________________________________________________________")
    print(echr_document.get_body())
    print("FOOTNOTES__________________________________________________________________________________________________")
    print(echr_document.get_footnotes())
    echr_document.body_to_txt(body_path)
    print("TITLES_____________________________________________________________________________________________________")
    echr_document.extract_titles()
    for t in echr_document.get_titles():
        print(t)
    print("TRIPLES____________________________________________________________________________________________________")
    echr_document.extract_triples_from_case_detail()
    print(echr_document.get_triples())
