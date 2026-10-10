import json
import boto3
from image_processor.processing import process_image

s3 = boto3.client("s3")

def lambda_handler(event, context):
    bucket = event["detail"]["bucket"]["name"]
    key = event["detail"]["object"]["key"]        # tmp/{uuid}/original.jpg
    folder = key.rsplit("/", 1)[0]
    try:
        original = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        s3.put_object(Bucket=bucket, Key=f"{folder}/processed.jpg",
                      Body=process_image(original), ContentType="image/jpeg")
    except Exception as e:
        # No se relanza: el backend lee error.json y así se evitan reintentos
        print(f"Error procesando {key}: {e}")
        s3.put_object(Bucket=bucket, Key=f"{folder}/error.json",
                      Body=json.dumps({"error": str(e)}), ContentType="application/json")
