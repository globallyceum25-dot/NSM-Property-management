"""Bulk property upload: the Excel template and the importer, over HTTP."""

import io
import re
import zipfile

from .support import RegisterTestCase

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

CSV_ROWS = (
    "Property name,Property type,Owning company,Tenure,District,Latitude,Longitude,"
    "Land extent,Land unit,Building area,Building unit,Acquisition date,Notes\n"
    "Maharagama Bus Yard,Bus Yards,NCGE,Freehold,Colombo,6.846,79.926,1.5,acres,12000,sq ft,15/08/2020,ok\n"
    "Kandy Hostel,Hostels,,Rented in,Kandy,7.29,80.63,,,,,,\n"
    "Swapped Coordinates,Warehouse,,Freehold,Galle,80.2,6.03,,,,,,\n"
    "No Type,,,Freehold,Kandy,7.29,80.63,,,,,,\n"
    "Unknown Company,Warehouse,XYZ,Freehold,Matara,5.95,80.55,,,,,,\n"
)


class BulkUploadTests(RegisterTestCase):

    def upload(self, filename, data, mode="check", content_type="text/csv"):
        return self.request("POST", "/api/import/properties", data={"mode": mode},
                            files={"file": (filename, data, content_type)})

    def property_count(self):
        return len(self.get("/api/properties"))

    def test_template_is_a_workbook_built_from_the_register(self):
        response = self.request("GET", "/api/import/template.xlsx")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], XLSX)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        book = zipfile.ZipFile(io.BytesIO(response.body))
        workbook = book.read("xl/workbook.xml").decode()
        self.assertEqual(re.findall(r'<sheet name="([^"]+)"', workbook),
                         ["Properties", "Instructions", "Example", "Lists"])
        sheet = book.read("xl/worksheets/sheet1.xml").decode()
        required = re.findall(r'<c r="[A-Z]+1" t="inlineStr" s="2"><is><t>([^<]*)</t>', sheet)
        self.assertEqual(required, ["Property name *", "Property type *", "Tenure *",
                                    "Latitude *", "Longitude *"])
        self.assertIn("<formula1>lst_types</formula1>", sheet)
        # The drop-downs offer the register's own property types.
        lists = book.read("xl/worksheets/sheet4.xml").decode()
        for sbu in self.get("/api/sbus"):
            self.assertIn(sbu["name"].replace("&", "&amp;"), lists)

    def test_check_reports_every_row_and_saves_nothing(self):
        before = self.property_count()
        result = self.ok("POST", "/api/import/properties", data={"mode": "check"},
                         files={"file": ("props.csv", CSV_ROWS.encode(), "text/csv")})
        self.assertEqual((result["total"], result["valid"], result["invalid"]), (5, 2, 3))
        problems = {r["name"]: r["errors"] for r in result["rows"] if not r["ok"]}
        self.assertIn("swapped", problems["Swapped Coordinates"][0]["message"])
        self.assertEqual(problems["No Type"][0]["column"], "Property type")
        self.assertEqual(problems["Unknown Company"][0]["column"], "Owning company")
        self.assertEqual(result["created"], [])
        self.assertEqual(self.property_count(), before)

    def test_import_saves_the_rows_that_pass(self):
        before = self.property_count()
        result = self.ok("POST", "/api/import/properties", expected=201, data={"mode": "import"},
                         files={"file": ("props.csv", CSV_ROWS.encode(), "text/csv")})
        self.assertEqual(len(result["created"]), 2)
        self.assertEqual(self.property_count(), before + 2)
        yard = self.get("/api/properties", q="Maharagama Bus Yard")[0]
        self.assertTrue(yard["property_code"].startswith("BUS-"))
        self.assertEqual(yard["sbu_name"], "Bus Yards")
        self.assertEqual(yard["entity_code"], "NCGE")
        self.assertEqual(yard["extent_sqft"], 65340)          # 1.5 acres
        self.assertEqual(yard["building_area_sqft"], 12000)
        self.assertEqual(yard["acquisition_date"], "2020-08-15")  # typed day first
        hostel = self.get("/api/properties", q="Kandy Hostel")[0]
        self.assertIsNone(hostel["legal_entity_id"])
        self.assertEqual(hostel["ownership_type"], "RENTED_IN")

    def test_the_templates_example_rows_import(self):
        template = self.request("GET", "/api/import/template.xlsx").body
        # Fill the Properties sheet with the Example sheet's rows.
        filled = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(template)) as src, zipfile.ZipFile(filled, "w") as out:
            for name in src.namelist():
                data = src.read(name)
                if name == "xl/worksheets/sheet1.xml":
                    data = src.read("xl/worksheets/sheet3.xml")
                out.writestr(name, data)
        result = self.ok("POST", "/api/import/properties", data={"mode": "check"},
                         files={"file": ("filled.xlsx", filled.getvalue(), XLSX)})
        self.assertEqual(result["sheet"], "Properties")
        self.assertEqual((result["total"], result["valid"]), (2, 2), result["rows"])

    def test_files_that_cannot_be_read(self):
        old = self.upload("old.xls", b"\xd0\xcf\x11\xe0 not really", content_type="application/vnd.ms-excel")
        self.assertEqual(old.status, 400)
        self.assertIn("Save As", old.json()["error"])
        broken = self.upload("broken.xlsx", b"not a zip", content_type=XLSX)
        self.assertEqual(broken.status, 400)
        self.assertIn(".xlsx", broken.json()["error"])
        headings = self.upload("wrong.csv", b"Name,Colour\nA,red\n")
        self.assertEqual(headings.status, 400)
        self.assertIn("missing required columns", headings.json()["error"])
        empty = self.upload("empty.csv", b"Property name,Property type,Tenure\n")
        self.assertEqual(empty.status, 400)
        self.assertIn("No properties found", empty.json()["error"])
        nothing = self.request("POST", "/api/import/properties", data={"mode": "check"}, files={})
        self.assertEqual(nothing.status, 400)
