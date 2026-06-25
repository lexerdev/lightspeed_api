import sys
import requests
import datetime
import json
import time
from urllib import parse

__author__ = "Forrest Beck"
REQUESTS_PER_SECOND = 1
RETRY_STATUS_CODES = [429, 104]

class LightSpeedJSONParseError(Exception):
    pass
class LightSpeedResponseError(Exception):
    pass

class LightSpeedAuthExpiredError(Exception):
    pass


class Lightspeed(object):

    def __init__(self, config):
        """
        Creates new Lightspeed object.
        :param config: Specify dictionary with config
        """
        self.config = config

        if "account_id" in config:
            self.api_url = "https://api.lightspeedapp.com/API/V3/Account/" + config["account_id"] + "/"
        else:
            self.api_url = ""

        self.bearer_token = config.get("access_token")

        self.rate_limit_bucket_level = None
        self.rate_limit_bucket_rate = 1
        self.rate_limit_last_request = datetime.datetime.now()

        # Create a new session for API calls. This will hold bearer token.
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json'})
        if self.bearer_token:
            self.session.headers.update({'Authorization': 'Bearer ' + self.bearer_token})

    def __repr__(self):
        return "Lightspeed API"

    def set_token(self, access_token):
        """
        Update the bearer token used for API calls.
        Called after re-auth via the dashboard.
        """
        self.bearer_token = access_token
        self.session.headers.update({'Authorization': 'Bearer ' + access_token})

    def request_bucket(self, method, url, data=None):
        """
        Sends request to session.  Ensures the request doesn't exceed the rate limits of the leaky bucket.
        :param method: post, get, put, delete
        :param url: complete api url
        :param data: post/put data
        :return: request object
        """

        if self.rate_limit_bucket_level is not None:
            units_available = float(self.rate_limit_bucket_level.split("/")[1]) - float(self.rate_limit_bucket_level.split("/")[0])
        else:
            units_available = 180

        if method in ("post", "put", "delete"):
            units_needed = 10
        else:
            units_needed = 1

        if not units_available >= units_needed:
                left_over = units_needed - units_available
                seconds_wait = left_over / self.rate_limit_bucket_rate
                last_request = datetime.timedelta.total_seconds(datetime.datetime.now() - self.rate_limit_last_request)
                if last_request < seconds_wait:
                    time.sleep(seconds_wait - last_request)

        last_response_text, last_status_code = None, None
        for tries in range(6):
            try:
                if method == "post":
                    s = self.session.post(url, data=data)
                elif method == "put":
                    s = self.session.put(url, data=data)
                elif method == "delete":
                    s = self.session.delete(url)
                elif method == "get":
                    s = self.session.get(url)

                if s.status_code == 200:
                    # Update time with latest request.
                    self.rate_limit_last_request = datetime.datetime.now()
                    # Update Bucket Levels
                    self.rate_limit_bucket_level = s.headers['X-LS-API-Bucket-Level']
                    # Update Drip Rates
                    self.rate_limit_bucket_rate = int(float(s.headers['X-LS-API-Drip-Rate']))
                    return s

                # Watch for too many requests status
                elif s.status_code in RETRY_STATUS_CODES:
                    time.sleep(REQUESTS_PER_SECOND)
                elif s.status_code == 401:
                    raise LightSpeedAuthExpiredError(
                        f"Authentication expired (401): {s.text}"
                    )
                else:
                    last_response_text, last_status_code = s.text, s.status_code
                    print(f"Unexpected status code {s.status_code}, message: {s.text}", file=sys.stderr)
            except requests.exceptions.HTTPError as e:
                print(f"HTTP error occurred on attempt {tries + 1}: {e}", file=sys.stderr)
                if tries >= 5:
                    raise e
            except Exception as e:
                print(f"Error occurred on attempt {tries + 1}: {type(e).__name__}: {e}", file=sys.stderr)
                if tries >= 5:
                    raise e
        else:
            raise LightSpeedResponseError(f'Received a non 200 status code: {last_status_code}, message: {last_response_text}')

    def get(self, source, parameters=None):
        """
        Get data from API. Implement pagination.
        :param source: API Source desired
        :param parameters: Optional URL Parameters.
        :return: JSON Results
        """
        if parameters:
            url = self.api_url + source + ".json?" + parse.urlencode(parameters, safe=':-')
        else:
            url = self.api_url + source + ".json"

        while True:
            r = self.request_bucket("get", url)
            yield r
            body = r.json()
            if not body.get('@attributes', {}).get('next'):
                break
            url = body['@attributes']['next']

    def create(self, source, data, parameters=None):
        """
        Create new object in API with POST.
        :param source: API Source
        :param data: POST Data
        :param parameters: Optional URL Parameters.
        :return: JSON Results
        """



        d = json.dumps(data)

        if parameters:
            url = self.api_url + source + ".json?" + parameters
        else:
            url = self.api_url + source + ".json"

        r = self.request_bucket("post", url, d)
        return r

    def update(self, source, data, parameters=None):
        """
        Update object in API using PUT
        :param source: API Source
        :param data: PUT Data
        :param parameters: Optional URL Parameters.
        :return: JSON Results
        """



        d = json.dumps(data)

        if parameters:
            url = self.api_url + source + ".json?" + parameters
        else:
            url = self.api_url + source + ".json"

        r = self.request_bucket("put", url, d)
        return r

    def delete(self, source, parameters=None):
        """
        Delete object from API
        :param source: API Source
        :param parameters: Optional URL Parameters.
        :return: JSON Results
        """
        if parameters:
            url = self.api_url + source + ".json?" + parameters
        else:
            url = self.api_url + source + ".json"

        r = self.request_bucket("delete", url)
        return r
