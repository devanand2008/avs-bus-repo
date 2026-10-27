from fleet.config import settings
def s3():
    import boto3
    return boto3.client('s3',endpoint_url=settings.S3_ENDPOINT_URL or None,aws_access_key_id=settings.S3_ACCESS_KEY,aws_secret_access_key=settings.S3_SECRET_KEY,region_name=settings.S3_REGION)
