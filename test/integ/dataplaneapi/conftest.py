# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0


import pytest
import boto3
import requests
import logging
import re
import os

from requests_aws4auth import AWS4Auth


# Fixture for retrieving env variables

@pytest.fixture(scope='session')
def testing_env_variables():
    print('Setting variables for tests')
    try:
        test_env_vars = {
            'MEDIA_PATH': os.environ['TEST_MEDIA_PATH'],
            'SAMPLE_IMAGE': os.environ['SAMPLE_IMAGE'],
            'REGION': os.environ['REGION'],
            'MI_STACK_NAME': os.environ['MI_STACK_NAME'],
            'ACCESS_KEY': os.environ['AWS_ACCESS_KEY_ID'],
            'SECRET_KEY': os.environ['AWS_SECRET_ACCESS_KEY']
        }

        # Optional session token may be set if we are using temporary STS credentials.
        session_token = os.environ.get('AWS_SESSION_TOKEN', '')
        if len(session_token):
            test_env_vars['SESSION_TOKEN'] = session_token

    except KeyError as e:
        logging.error("ERROR: Missing a required environment variable for testing: {variable}".format(variable=e))
        raise Exception(e)
    else:
        return test_env_vars


# Fixture for stack resources

@pytest.fixture(scope='session')
def stack_resources(testing_env_variables):
    print('Validating Stack Resources')
    resources = {}
    # is the dataplane api and bucket present?

    client = boto3.client('cloudformation', region_name=testing_env_variables['REGION'])
    response = client.describe_stacks(StackName=testing_env_variables['MI_STACK_NAME'])
    outputs = response['Stacks'][0]['Outputs']

    for output in outputs:
        resources[output["OutputKey"]] = output["OutputValue"]

    assert "DataplaneApiEndpoint" in resources
    assert "DataplaneBucket" in resources

    api_endpoint_regex = ".*.execute-api."+testing_env_variables['REGION']+".amazonaws.com/api/.*"

    assert re.match(api_endpoint_regex, resources["DataplaneApiEndpoint"])

    response = client.describe_stacks(StackName=resources["TestStack"])

    outputs = response['Stacks'][0]['Outputs']
    for output in outputs:
        resources[output["OutputKey"]] = output["OutputValue"]

    return resources


# This fixture uploads the sample media objects for testing.
@pytest.fixture(scope='session', autouse=True)
def upload_media(testing_env_variables, stack_resources):
    print('Uploading Test Media')
    s3 = boto3.client('s3', region_name=testing_env_variables['REGION'])
    # Upload test media files
    s3.upload_file(testing_env_variables['MEDIA_PATH'] + testing_env_variables['SAMPLE_IMAGE'], stack_resources['DataplaneBucket'], 'upload/' + testing_env_variables['SAMPLE_IMAGE'])
    # Wait for fixture to go out of scope:
    yield upload_media


@pytest.mark.usefixtures("upload_media")
class API:
    def __init__(self, stack_resources, testing_env_variables):
        self.env_vars = testing_env_variables
        self.stack_resources = stack_resources
        self.auth = AWS4Auth(testing_env_variables['ACCESS_KEY'], testing_env_variables['SECRET_KEY'],
                             testing_env_variables['REGION'], 'execute-api',
                             session_token=testing_env_variables.get('SESSION_TOKEN'))

        # aws_access_key = testing_env_variables['ACCESS_KEY'],
        # aws_secret_access_key = testing_env_variables['SECRET_KEY'],
        # aws_host = stack_resources['DataplaneApiEndpoint'].split('/')[0],
        # aws_region = testing_env_variables['REGION'],
        # aws_service = 'execute-api'

    # dataplane methods

    def create_asset(self):
        headers = {"Content-Type": "application/json"}
        body = {
            "Input": {
                "MediaType": "Image",
                "S3Bucket": self.stack_resources['DataplaneBucket'],
                "S3Key": "upload/" + self.env_vars['SAMPLE_IMAGE']
            }
        }

        print("POST /create")
        create_asset_response = requests.post(self.stack_resources["DataplaneApiEndpoint"] + '/create', headers=headers, json=body, verify=True, auth=self.auth)
        return create_asset_response

    def post_metadata(self, asset_id, metadata, paginate=False, end=False):
        if paginate is True and end is True:
            url = self.stack_resources["DataplaneApiEndpoint"] + 'metadata/' + asset_id + "?paginated=true&end=true"
        elif paginate is True and end is False:
            url = self.stack_resources["DataplaneApiEndpoint"] + 'metadata/' + asset_id + "?paginated=true"
        else:
            url = self.stack_resources["DataplaneApiEndpoint"] + 'metadata/' + asset_id

        headers = {"Content-Type": "application/json"}
        body = metadata
        print("POST /metadata/{asset}".format(asset=asset_id))
        nonpaginated_metadata_response = requests.post(url, headers=headers, json=body, verify=True, auth=self.auth)
        return nonpaginated_metadata_response

    def checkout_asset(self, asset_id):
        headers = {"Content-Type": "application/json"}
        body = {"LockedBy": "user01@example.com"}
        print("POST /checkout/{asset}".format(asset=asset_id))
        response = requests.post(self.stack_resources["DataplaneApiEndpoint"] + '/checkout/' + asset_id, headers=headers, json=body, verify=True, auth=self.auth)
        return response

    def list_checkouts(self):
        headers = {"Content-Type": "application/json"}
        print("GET /checkouts")
        response = requests.get(self.stack_resources["DataplaneApiEndpoint"] + '/checkouts', headers=headers, verify=True, auth=self.auth)
        return response

    def checkin_asset(self, asset_id):
        headers = {"Content-Type": "application/json"}
        print("POST /checkout/{asset}".format(asset=asset_id))
        response = requests.post(self.stack_resources["DataplaneApiEndpoint"] + '/checkin/' + asset_id, headers=headers, verify=True, auth=self.auth)
        return response

    def get_all_metadata(self, asset_id, cursor=None):

        url = self.stack_resources["DataplaneApiEndpoint"] + 'metadata/' + asset_id
        headers = {"Content-Type": "application/json"}
        print("GET /metadata/{asset}".format(asset=asset_id))

        if cursor is None:
            print("GET /metadata/{asset}".format(asset=asset_id))
            metadata_response = requests.get(url, headers=headers, verify=True, auth=self.auth)
        else:
            print("GET /metadata/{asset}?cursor={cursor}".format(asset=asset_id, cursor=cursor))
            query_params = {"cursor": cursor}
            metadata_response = requests.get(url, headers=headers, params=query_params, verify=True, auth=self.auth)

        print(metadata_response.json())
        print(metadata_response.text)
        return metadata_response

    def get_single_metadata_field(self, asset_id, operator):
        metadata_field = operator["OperatorName"]
        url = self.stack_resources["DataplaneApiEndpoint"] + 'metadata/' + asset_id + "/" + metadata_field
        headers = {"Content-Type": "application/json"}
        print("GET /metadata/{asset}/{operator}".format(asset=asset_id, operator=operator["OperatorName"]))
        single_metadata_response = requests.get(url, headers=headers, verify=True, auth=self.auth)
        return single_metadata_response

    def delete_single_metadata_field(self, asset_id, operator):
        metadata_field = operator["OperatorName"]
        url = self.stack_resources["DataplaneApiEndpoint"] + 'metadata/' + asset_id + "/" + metadata_field
        headers = {"Content-Type": "application/json"}
        print("DELETE /metadata/{asset}/{operator}".format(asset=asset_id, operator=operator["OperatorName"]))
        delete_single_metadata_response = requests.delete(url, headers=headers, verify=True, auth=self.auth)
        return delete_single_metadata_response

    def delete_asset(self, asset_id):
        url = self.stack_resources["DataplaneApiEndpoint"] + 'metadata/' + asset_id
        headers = {"Content-Type": "application/json"}
        print("DELETE /metadata/{asset}".format(asset=asset_id))
        delete_asset_response = requests.delete(url, headers=headers, verify=True, auth=self.auth)
        return delete_asset_response


@pytest.fixture(scope='session')
def dataplane_api(stack_resources, testing_env_variables):
    def _gen_api():
        print('Generating a dataplane API object for testing')
        testing_api = API(stack_resources, testing_env_variables)
        return testing_api
    return _gen_api
