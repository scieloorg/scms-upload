import os
import glob
import logging


def delete_files(file_path):
    if not file_path:
        return
    try:
        os.unlink(file_path)
    except Exception as e:
        pass

    basename = os.path.basename(file_path)
    if "_" not in basename:
        return

    try:
        suffix = basename.split("_")[-1]
        pattern = file_path.split(suffix)[0][:-1] + "*"
        logging.info(f"deleting files with pattern: {pattern}")
        for path in glob.glob(pattern):
            try:
                os.unlink(path)
            except Exception as e:
                logging.exception(e)
    except Exception as e:
        logging.exception(e)