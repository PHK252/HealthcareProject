import boto3

BUCKET_NAME = "amzn-s3-docdemo-bucket"

s3 = boto3.client(
    "s3",
    region_name="us-east-2"
)

# 1. Upload a test object
test_content = b"CareBridge S3 integration successful!"

s3.put_object(
    Bucket=BUCKET_NAME,
    Key="tests/test.txt",
    Body=test_content
)

print("Upload successful!")

# 2. Retrieve the object
response = s3.get_object(
    Bucket=BUCKET_NAME,
    Key="tests/test.txt"
)

downloaded_content = response["Body"].read()

print("Downloaded:", downloaded_content.decode())

# 3. Verify the contents
assert downloaded_content == test_content

print("Verification successful!")

# 4. Delete the test object
s3.delete_object(
    Bucket=BUCKET_NAME,
    Key="tests/test.txt"
)

print("Test object deleted.")