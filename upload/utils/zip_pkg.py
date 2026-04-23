import os
import logging
from tempfile import TemporaryDirectory, mkdtemp
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile


class PkgZip:

    def __init__(self, file_path):
        self.file_path = file_path

    def split(self):
        found = False
        with ZipFile(self.file_path) as zf:
            xml_and_related_items = self.get_zip_content(zf)
            pkgs = self.get_packages(
                xml_and_related_items["xmls"],
                xml_and_related_items["other_files"]
            )
            for xml_name, items in pkgs.items():
                yield self.zip_package(zf, xml_name, items)

    def get_zip_content(self, zf):
        file_paths = set(zf.namelist() or [])
        logging.info(f"file_paths: {file_paths}")

        other_files = {}
        xmls = {}
        for file_path in file_paths:
            basename = os.path.basename(file_path)
            if basename.startswith("."):
                continue
            name, ext = os.path.splitext(basename)
            data = {"file_path": file_path, "basename": basename}
            logging.info(f"{self.file_path} {data}")
            if ext == ".xml":
                xmls.setdefault(name, [])
                xmls[name].append(data)
            else:
                other_files.setdefault(name, [])
                other_files[name].append(data)
        return {"xmls": xmls, "other_files": other_files}

    def get_packages(self, xmls, other_files):
        for k, v in xmls.items():
            logging.info((k, v))
        for k, v in other_files.items():
            logging.info((k, v))

        other_files_keys = list(other_files.keys())
        for key in xmls.keys():
            for other_files_key in other_files_keys:
                logging.info(f"{key} | {other_files_key}")
                if key == other_files_key:
                    logging.info("a")
                    xmls[key].extend(other_files.pop(other_files_key))
                elif other_files_key.startswith(key + "-"):
                    logging.info("b")
                    xmls[key].extend(other_files.pop(other_files_key))
                else:
                    logging.info("c")
        return xmls

    def zip_package(self, zf, xml_name, files):
        try:
            content = None
            with TemporaryDirectory() as tmpdirname:
                zfile = os.path.join(tmpdirname, f"{xml_name}.zip")
                with ZipFile(zfile, "w", compression=ZIP_DEFLATED) as zfw:
                    for item in files:
                        zfw.writestr(
                            item["basename"], zf.read(item["file_path"])
                        )
                with open(zfile, "rb") as zfw:
                    content = zfw.read()
            return {"xml_name": xml_name, "content": content}
        except Exception as exc:
            logging.exception(exc)
            return {"xml_name": xml_name, "error": str(exc)}
