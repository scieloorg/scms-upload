from django.core.files.storage import FileSystemStorage

from django.contrib.auth import get_user_model

from config import celery_app

import zipfile


User = get_user_model()


@celery_app.task(bind=True,  max_retries=3)
def get_files_list(self, file):
    fss = FileSystemStorage()

    file = fss.path(file.path)

    try:
        with zipfile.ZipFile(file, 'r') as zip_content:
            return zip_content.namelist()
    except zipfile.BadZipFile:
        return []
