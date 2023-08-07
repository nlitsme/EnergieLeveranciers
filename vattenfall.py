#!/usr/bin/python3
"""
This tool requests the hourly usage as displayed in your vattenfall account.
vattenfall keeps a record of about 3 months history.

I did not yet implement the authentication process, so you will need to
manually extract the auth code and customerid from your browser, for instance
by looking at requests in the debug view.
"""
import re
import urllib.request
import urllib.parse
import http.cookiejar
import json
from datetime import datetime, timezone, timedelta
import binascii


class Vattenfall:
    def __init__(self, args):
        self.args = args
        # from: https://www.vattenfall.nl/service/mijn-vattenfall/main.efd1d01bec9ac539.js
        # 814633e3eccb4bcc931190267d169b52  chatbotSubscriptionKey: chatbotEndpoint: "https://api.vattenfall.nl/chatbot-api",
        # 93420a9dd01a49c1878ac484379c332d  ocpApimSubscriptionJourneyTopicBaseKey:  apiJourneyTopicBaseUrl: "https://api.vattenfall.nl/journeytopicapi/v1",
        # 96d00cf46aee4f4a8f9caf4e179e7685  ocpApimSubscriptionFeaturesBaseKey: apiFeaturesBaseUrl: "https://api.vattenfall.nl/featuresprd/api",
        # f5406a12dbdd41a2ad8e0de5a69d9e00  ocpApimSubscriptionBaseKey: apiBaseUrl: "https://api.vattenfall.nl/api/mijnnuonprd/v2",

        self.apikey = "f5406a12dbdd41a2ad8e0de5a69d9e00"
        self.auth = args.auth
        # apiBaseUrl: "https://api.vattenfall.nl/api/mijnnuonprd/v2",
        self.baseurl = "https://api.vattenfall.nl/api/mijnnuonprd/v2"

        # customer_id / ?
        self.customerid = args.customerid

        handlers = []
        if args.debug:
            handlers.append(urllib.request.HTTPSHandler(debuglevel=1))
        self.opener = urllib.request.build_opener(*handlers)

    def logprint(self, *args):
        if self.args.debug:
            print(*args)

    def httpreq(self, url, data=None):
        """
        Generic http request function.
        Does a http-POST when the 'data' argument is present.

        Adds the nesecesary xsrf and auth headers.
        """
        self.logprint(">", url)
        hdrs = { }
        if data and type(data)==str:
            data = data.encode('utf-8')
        hdrs["Content-Type"] = "application/json"
        if self.apikey:
            hdrs["Ocp-Apim-Subscription-Key"] = self.apikey
        if self.auth:
            hdrs['Authorization'] = "Bearer " + self.auth
        req = urllib.request.Request(url, headers=hdrs)
        kwargs = dict()
        if data:
            kwargs["data"] = data

        for tries in range(3):
            try:
                response = self.opener.open(req, **kwargs)
            except urllib.error.HTTPError as e:
                self.logprint("!", str(e))
                response = e
            try:
                data = response.read()
            except http.client.IncompleteRead as e:
                print("retrying - %s" % e)
                continue
            if response.headers.get("content-type", '').find("application/json")>=0:
                js = json.loads(data)
                self.logprint(js)
                self.logprint()
                return js
            self.logprint(data)
            self.logprint()
            return data
    def login(self, username, password):
        captchatoken = ""  # TODO: get this from browser.
        q = {
	'email': username,
	'password': password,
	'sessionDataKey': sessiondatakey,
	'requestDevice': 'Firefox:desktop:GNU/Linux',
	'captchaToken': captchatoken,
	'tenantDomain': 'nl.b2c.customers',
        }
        self.httpreq('https://accounts.vattenfall.nl/iamng/nlb2c-revamp/commonauth', urllib.parse.urlencode(q))
        # "redirect": "https://accounts.vattenfall.nl/iamng/nlb2c-revamp/oauth2/authorize?sessionDataKey=..."
        #  -> wrong credentials.

        # https://api.vattenfall.nl/chatbot-api/session/start
        #   json: sessionId

    def getusage(self, tstart, tend, interval):
        """
        NOTE: tend is inclusive
        """
        start = f"{tstart:%Y-%m-%d}"
        end = f"{tend:%Y-%m-%d}"
        q = dict(
                # 5 = uur, 6 = jaar, 1 = maand, 3 = ?dag?
            Interval = interval,
            GetAggregatedResults = False,
            GetAmountDetails = False,
            GetAmounts = True,
            GetRoundedAmounts = False,
            GetComparedConsumption = False,
            DateFrom = start,
            DateTo = end)
        return self.httpreq(f"{self.baseurl}/consumptions/consumptions/{self.customerid}/{interval}/?"+urllib.parse.urlencode(q))


def decode_datetime(t):
    return datetime.strptime(t, "%Y-%m-%d")

def loadconfig(cfgfile):
    """
    Load config from .energierc
    """
    with open(cfgfile, 'r') as fh:
        txt = fh.read()
    txt = "[root]\n" + txt
    import configparser
    config = configparser.ConfigParser()
    config.read_string(txt)

    return config


def applyconfig(cfg, args):
    """
    Apply the configuration read from .energierc to the `args` dictionary,
    which is used to configure everything.
    """
    if not args.username and cfg.has_option('vattenfall', 'user'):
        args.username = cfg.get('vattenfall', 'user')
    if not args.password and cfg.has_option('vattenfall', 'pass'):
        args.password = cfg.get('vattenfall', 'pass')
    if not args.auth and cfg.has_option('vattenfall', 'auth'):
        args.auth = cfg.get('vattenfall', 'auth')
    if not args.customerid and cfg.has_option('vattenfall', 'customerid'):
        args.customerid = cfg.get('vattenfall', 'customerid')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Vattenfall per hour info')
    parser.add_argument('--debug', '-d', action='store_true', help='print all intermediate steps')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--insights', action='store_true')
    parser.add_argument('--products', action='store_true')
    parser.add_argument('--peruur', action='store_true')
    parser.add_argument('--perdag', action='store_true')
    parser.add_argument('--permaand', action='store_true')
    parser.add_argument('--perjaar', action='store_true')
    parser.add_argument('--since', '--from', type=str, help='get usage from')
    parser.add_argument('--until', type=str, help='get usage until, default=now')
    parser.add_argument('--weeks', '-n', type=int, default=0)
    parser.add_argument('--username', '-u', type=str)
    parser.add_argument('--password', '-p', type=str)
    parser.add_argument('--auth', type=str)
    parser.add_argument('--customerid', type=str)
    parser.add_argument('--config', help='specify configuration file.', default='~/.energierc')
    args = parser.parse_args()

    if args.config.startswith("~/"):
        import os
        homedir = os.environ['HOME']
        args.config = args.config.replace("~", homedir)

    try:
        cfg = loadconfig(args.config)

        applyconfig(cfg, args)
    except Exception as e:
        print("Error in config: %s" % e)

    if args.username or args.password:
        print("login with username/password not yet supported")
        return

    en = Vattenfall(args)

    #if not en.login(args.username, args.password):
    #    return

    t0 = None
    t1 = datetime.now()
    td = timedelta(days=7)
    if args.peruur:
        td = timedelta(days=7)
    elif args.perdag:
        td = timedelta(days=31)
    elif args.permaand:
        td = timedelta(days=366)

    if args.since:
        t0 = decode_datetime(args.since)
    if args.until:
        t1 = decode_datetime(args.until)
    if args.weeks and args.since and args.until:
        print("can specify only two out of weeks, since and until")
        return
    if t1 is None:
        t1 = t0 + td*args.weeks
    if t0 is None:
        t0 = t1 - td*args.weeks

    interval = 5
    if args.peruur:
        interval = 5
    elif args.perdag:
        interval = 3
    elif args.permaand:
        interval = 1
    elif args.perjaar:
        interval = 6

    if t0==t1:
        print("nothing to do, specify nr of weeks(-w), or --from + --until")
        return
    t = t0
    while t < t1:
        j = en.getusage(t, t+td-timedelta(days=1), interval)
        print(json.dumps(j))
        t += td


if __name__ == '__main__':
    main()
