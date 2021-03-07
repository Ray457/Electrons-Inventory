import threading
import configparser
from datetime import datetime
import webbrowser
import http.server
import socketserver
from urllib.parse import parse_qs, urlparse, urlencode
import requests
import ssl

AUTH_RESP_PORT = 4443


class DKAPIInterface:
    def __init__(self, auth_complete_callback=None):
        # constants
        self.CONFIG_FILENAME = "AppData/inventory.ini"
        self.CLIENT_ID = ""
        self.CLIENT_SECRET = ""
        '''
        # sandbox
        self.REDIRECT_URL = "http://127.0.0.1:{}".format(AUTH_RESP_PORT)
        self.AUTH_URL = "https://sandbox-api.digikey.com/v1/oauth2/authorize?"\
                    "response_type=code&"\
                    "client_id={}&"\
                    "redirect_uri={}".format(CLIENT_ID, REDIRECT_URL)
        self.ACCESS_URL = "https://sandbox-api.digikey.com/v1/oauth2/token"  # same for access and refresh tokens

        self.PRODUCT2DBARCODE_URL = "https://sandbox-api.digikey.com/Barcoding/v3/Product2DBarcodes/"
        '''
        self.REDIRECT_URL = "https://127.0.0.1:{}".format(AUTH_RESP_PORT)  # production
        self.AUTH_URL = "https://api.digikey.com/v1/oauth2/authorize?" \
                        "response_type=code&" \
                        "client_id={}&" \
                        "redirect_uri={}".format(self.CLIENT_ID, self.REDIRECT_URL)
        self.ACCESS_URL = "https://api.digikey.com/v1/oauth2/token"  # same for access and refresh tokens

        self.PRODUCT2DBARCODE_URL = "https://api.digikey.com/Barcoding/v3/Product2DBarcodes/"

        # http server objects to serve the redirect URI at localhost
        self.http_handler = None
        self.http_thread = None
        self.httpd = None

        # tokens for the API
        self.access_token = ""
        self.refresh_token = ""
        self.access_token_expiry = 0
        self.refresh_token_expiry = 0
        self.auth_valid = False
        self.refresh_valid = False

        # try to read the config file
        self.config = configparser.ConfigParser()
        open_cfg_ret = self.config.read(self.CONFIG_FILENAME)
        # returns a list. If the file exists, the list contains the file name, nothing otherwise.
        config_len = len(open_cfg_ret)
        if config_len == 0:
            self.prompt_app_creation()
        if config_len > 0:
            # config file is present. Will assume it has the correct content
            try:  # test for the client credentials
                self.CLIENT_ID = self.config["client_cred"]["id"]
                self.CLIENT_SECRET = self.config["client_cred"]["secret"]
            except KeyError:
                self.prompt_app_creation()

            self.load_tokens()

            # check if the tokens are valid
            self.check_access_token()

        # callback that gets called when the user authorisation is complete
        self.auth_complete_callback = auth_complete_callback

    def prompt_app_creation(self):
        print("Admin: please create a DigiKey application to use this program. Refer to README for details.")
        input("Press Enter to Exit..")
        exit(0)

    def load_tokens(self):
        self.access_token = self.config["tokens"]["access_token"]
        self.refresh_token = self.config["tokens"]["refresh_token"]
        self.access_token_expiry = int(self.config["tokens"]["access_expiry"])
        self.refresh_token_expiry = int(self.config["tokens"]["refresh_expiry"])

    def save_tokens(self):
        if len(self.config.sections()) == 0:  # config file was not present
            self.config["tokens"] = {}
        self.config["tokens"]["access_token"] = \
            "{}".format(self.access_token)  # has to store in str
        self.config["tokens"]["access_expiry"] = \
            "{}".format(self.access_token_expiry)
        self.config["tokens"]["refresh_token"] = \
            "{}".format(self.refresh_token)
        self.config["tokens"]["refresh_expiry"] = \
            "{}".format(self.refresh_token_expiry)
        # write to file
        with open(self.CONFIG_FILENAME, 'w') as f_config:
            self.config.write(f_config)
            print("Saved auth config")

    def authorise(self):
        """
        Takes the user through the Digi-Key authorisation process.
        :return:
        """
        if self.http_thread is None:  # server not started
            # start the web server to handle the redirected web request after OAuth 2 authorisation completes
            self.httpd = socketserver.TCPServer(("127.0.0.1", AUTH_RESP_PORT),
                                                auth_resp_handler_factory(dk_api=self))
            # HTTPS code reference: https://gist.github.com/dergachev/7028596
            self.httpd.socket = ssl.wrap_socket(self.httpd.socket, certfile="./server.pem", server_side=True)
            self.http_thread = threading.Thread(target=self.httpd.serve_forever)
            self.http_thread.daemon = True
            self.http_thread.start()  # run the basic web server in another thread

        # start the user browser to begin the authorisation process
        webbrowser.open(self.AUTH_URL)

    def get_access_token(self, auth_code: str):
        """
        Gets the access token from Digi-Key and stores them into the object attributes
        :param auth_code: authorisation code for getting the access token
        :return: success: bool, True if the operation succeeded
                 resp: requests.models.response, the full response object in case error occurred
        """
        success = False
        req_str = "code=" \
                  "{}&" \
                  "client_id=" \
                  "{}&" \
                  "client_secret=" \
                  "{}&" \
                  "redirect_uri=" \
                  "{}&" \
                  "grant_type=authorization_code".format(auth_code,
                                                         self.CLIENT_ID,
                                                         self.CLIENT_SECRET,
                                                         self.REDIRECT_URL)
        print("Requesting access token...")
        access_resp = requests.post(url=self.ACCESS_URL,
                                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                                    data=req_str)
        if access_resp.status_code == 200:  # OK
            # extract and store tokens
            access_resp_json = access_resp.json()

            # calculate when the access and refresh tokens will expire
            time_now = int(datetime.now().timestamp())  # current time in unix timestamp format
            access_expiry = time_now + int(access_resp_json["expires_in"])
            refresh_expiry = time_now + int(access_resp_json["refresh_token_expires_in"])

            # store tokens
            self.access_token = access_resp_json["access_token"]
            self.refresh_token = access_resp_json["refresh_token"]
            self.access_token_expiry = access_expiry - 10  # offset for some leeway
            self.refresh_token_expiry = refresh_expiry - 10

            # save into the config file
            self.save_tokens()

            # update status flag
            self.auth_valid = True
            self.refresh_valid = True

            print("Successfully got the access and refresh tokens:")
            print(self.access_token)

            success = True

        return success, access_resp

    def refresh_access_token(self):
        success = False
        req_str = "client_id=" \
                  "{}&" \
                  "client_secret=" \
                  "{}&" \
                  "refresh_token=" \
                  "{}&" \
                  "grant_type=refresh_token".format(self.CLIENT_ID,
                                                    self.CLIENT_SECRET,
                                                    self.refresh_token)
        print("Requesting refresh token...")
        refresh_resp = requests.post(url=self.ACCESS_URL,
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'},
                                     data=req_str)
        if refresh_resp.status_code == 200:  # OK
            # extract and store tokens
            refresh_resp_json = refresh_resp.json()

            # calculate when the access and refresh tokens will expire
            time_now = int(datetime.now().timestamp())  # current time in unix timestamp format
            access_expiry = time_now + int(refresh_resp_json["expires_in"])
            refresh_expiry = time_now + int(refresh_resp_json["refresh_token_expires_in"])

            # store tokens
            self.access_token = refresh_resp_json["access_token"]
            self.refresh_token = refresh_resp_json["refresh_token"]
            self.access_token_expiry = access_expiry - 10  # offset for some leeway
            self.refresh_token_expiry = refresh_expiry - 10

            print("Successfully got the access and refresh tokens:")
            print(self.access_token)
            
            # save into the config file
            self.save_tokens()

            # update status flag
            self.auth_valid = True
            self.refresh_valid = True

            success = True

        return success, refresh_resp

    def check_access_token(self):
        timestamp_now = int(datetime.now().timestamp())

        if timestamp_now > self.refresh_token_expiry:  # need to perform another user authorisation
            print("Refresh token has expired")
            self.refresh_valid = False
        else:  # refresh token is still valid
            self.refresh_valid = True

        if timestamp_now > self.access_token_expiry:  # access token needs refreshing
            print("Access token has expired")
            # if the refresh token is expired, the access token will be expired too
            self.auth_valid = False
            if self.refresh_valid:
                success, resp = self.refresh_access_token()
                if not success:
                    print("Failed to refresh the access token! Full response:")
                    print(resp.json())
                else:  # successfully refreshed token
                    print("Successfully refreshed the access token")
                    self.auth_valid = True
        else:  # access token is still valid
            self.auth_valid = True

    def product_2d_barcode(self, dmtx_bytes: bytes):
        success = False
        self.check_access_token()

        encoded_dmtx = urlencode([("", dmtx_bytes)])[1:]  # URL encode into an argument pair then trim out the "="
        url = "{}{}".format(self.PRODUCT2DBARCODE_URL,
                            encoded_dmtx)
        barcode2d_resp = requests.get(url,
                                      headers={
                                          "accept": "application/json",
                                          "Authorization": "Bearer {}".format(self.access_token),
                                          "X-DIGIKEY-Client-Id": "{}".format(self.CLIENT_ID)
                                      })
        if barcode2d_resp.status_code == 200:  # OK
            success = True
        return success, barcode2d_resp


# class factory to link the html handler with the GUI and to pass information around
def auth_resp_handler_factory(dk_api: DKAPIInterface):
    class AuthRespHandler(http.server.SimpleHTTPRequestHandler):
        """
        This is basically the redirect URI server on localhost
        """
        def do_GET(self):  # handle the return data from Digi-Key authentication
            query = urlparse(self.path).query  # query string from the callback URL
            auth_results = parse_qs(query, keep_blank_values=True)

            resp_html = ""
            skip_write_html = False

            # check if the auth code is all good
            try:
                error_message = auth_results["error"]
                resp_html = """<p style="text-align: center;"><span style="color: #ff6600;">
                <strong>Failed to authorise.</strong></span></p>
                <p style="text-align: center;"><span style="color: #000000;">
                <strong>Message:
                {}
                </strong></span></p>
                <p style="text-align: center;"><span style="color: #000000;">
                <strong>Click <a href="
                {}
                ">here</a> if you would like to try again.</strong></span></p>""".format(
                    error_message, dk_api.AUTH_URL)
            except KeyError:  # no error in the response
                pass

            if resp_html == "":  # no error in the response, try get the access and refresh token
                try:
                    auth_code = auth_results["code"][0]
                    print("Success! Auth code: " + auth_code)
                    access_success, access_resp = dk_api.get_access_token(auth_code=auth_code)
                    if access_success:  # successfully got the access token
                        resp_html = """<p style="text-align: center;"><span style="color: #008000;">
                        <strong>Success!</strong></span></p>
                        <p style="text-align: center;">You can close this window now.</p>"""
                        if dk_api.auth_complete_callback is not None:
                            dk_api.auth_complete_callback()
                    else:
                        resp_html = """<p style="text-align: center;"><span style="color: #ff6600;">
                        <strong>Something went wrong...</strong></span></p>
                        <p style="text-align: center;"><span style="color: #000000;"><strong>Error code:</strong>
                        {}
                        </span></p>
                        <p style="text-align: center;"><span style="color: #000000;"><strong>Message:</strong>
                        {}
                        </span></p>
                        <p style="text-align: center;"><span style="color: #000000;"><strong>Details:</strong>
                        {}
                        </span></p>
                        <p style="text-align: center;"><span style="color: #000000;">Try again <a href="
                        {}
                        ">here</a>.</span></p>""".format(access_resp.status_code,
                                                         access_resp.json()["ErrorMessage"],
                                                         access_resp.json()["ErrorDetails"],
                                                         dk_api.AUTH_URL)
                        print("FAILED:" + str(access_resp.json()))
                except KeyError:
                    skip_write_html = True  # not a success request, likely is for favicon

            # generate index.html
            if not skip_write_html:
                with open("index.html", 'w') as f:
                    f.write(resp_html)

            # serve the generated index.html
            super().do_GET()
    return AuthRespHandler
