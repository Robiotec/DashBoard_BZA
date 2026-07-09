from urllib.parse import quote

from storages.backends.s3boto3 import S3Boto3Storage


class MinioMediaStorage(S3Boto3Storage):
    file_overwrite = True

    def get_available_name(self, name, max_length=None):
        if self.exists(name):
            self.delete(name)
        return name

    def url(self, name, parameters=None, expire=None, http_method=None):
        return f"/media-minio/{quote(name)}"
