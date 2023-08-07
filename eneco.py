#!/usr/bin/python3
"""
This tool extracts the hourly energy usage data as recorded by eneco.

Authentication works most of the time with username/password, but
occasionally eneco wants you to verify yourself using a token sent to your email address.
"""
import re
import urllib.request
import urllib.parse
import http.cookiejar
import json
from datetime import datetime, timezone, timedelta
import binascii


class Eneco:
    def __init__(self, args):
        self.args = args
        """
          The apikey is from "https://www.eneco.nl/" -> 'private'
          window.__SSR_CONTEXT__.globalKeys = {
          ...
          "digitalCore": { "baseUrl": "https://api-digital.enecogroup.com", "public": "6e01459668e74ab5b36907f058cea86b", "private": "dbf449cfdcf04a3d8913f4e7a2b297d3" },
          "apigee":      { "baseUrl": "https://api.enecogroup.com", "apiKey": "YSyTaZjOvj8ZqCR0LZ2cF73W9m3Yqjux" }
          ...
          }

        2023-07-13:  apikey is now FE_DC_API_KEY from window.__ENV in https://www.eneco.nl/mijn-eneco/
        """
        self.apikey = "41ff1058fc7f4446b80db84e8857c347"
        self.auth = None
        self.baseurl = "https://api-digital.enecogroup.com"
        self.customerid = None

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
            hdrs["apikey"] = self.apikey
        if self.auth:
            hdrs['Authorization'] = self.auth
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
                continue
            if response.headers.get("content-type", '').find("application/json")>=0:
                js = json.loads(data)
                self.logprint(js)
                self.logprint()
                return js
            self.logprint(data)
            self.logprint()
            return data
        raise Excepion("failed to connect to eneco")

    def unescapestring(self, txt):
        return re.sub(r'\\x(\w\w)', lambda m:chr(int(m[1], 16)), txt)
    def extractToken(self, html):
        if m := re.search(r'"stateToken":"(.*?)"', html.decode('utf-8')):
            return self.unescapestring(m[1])

    def extractIdToken(self, html):
        if m := re.search(r'name="id_token" value="(.*?)"', html.decode('utf-8')):
            return self.unescapestring(m[1])

    def extractCustomerId(self, html):
        if m := re.search(r'customerId: (\d+)', html.decode('utf-8')):
            return int(m[1])
        if m := re.search(r'clientId: "(\d+)"', html.decode('utf-8')):
            return int(m[1])

    def extractCustomerIdFromToken(self, token):
        a, b, c = token.split('.', 2)

        props = json.loads(binascii.a2b_base64(b+"===="))
        return props.get('klantnummer') or props.get('customerId')

    def dump_auth_status(self, auth):
        print("auth: status = %s : %s" % (auth.get('status'), ", ".join(auth.get('_links', {}).keys())))
        for f in auth.get('_embedded',{}).get('factors',[]):
            print(" factor %s : %s" % (f.get('factorType'), ", ".join(f.get('_links', {}).keys())))

    def login(self, username, password):
        """
/api/v1/sessions/me
/api/v1/sessions/me/lifecycle/refresh
/api/v1/interact
/api/v1/authorize
/api/v1/userinfo
/api/v1/token
/api/v1/authn/introspect

see exhar/eu1static.oktacdn.com/assets/js/sdk/okta-signin-widget/6.4.3/js/okta-sign-in.min-1.js
        """
        # html = self.httpreq("https://www.eneco.nl/mijn-eneco/")
        #  (20221223) -> now redirects to /identity/login/website_eneco_main/OktaNL?returnUrl=/mijn-eneco/
        html = self.httpreq("https://mijn.eneco.nl/")
        # -> redir to /login?returnUrl=...
        # -> redir to https://inloggen.eneco.nl/oauth2
        # extract 'oktaData' -> signIn -> stateToken
        token = self.extractToken(html)
        if not token:
            print("WARNING: failed to get token from mijn.eneco.nl main page")
            print(html)
            return

        # note: optional steps:  introspect  and device/nonce

        # NOTE: when passing a null stateToken to 'authn', you get a sessionToken from 'password/verify'  instead of the step-up redirect.
        auth1 = self.httpreq("https://inloggen.eneco.nl/api/v1/authn", json.dumps( {"username":username,"options":{"warnBeforePasswordExpired":True,"multiOptionalFactorEnroll":True},"stateToken":token}))
        if self.args.verbose:
            self.dump_auth_status(auth1)
        # check if status == UNAUTHENTICATED
        if auth1.get('status') != 'UNAUTHENTICATED':
            return
        # todo: _embedded.factors.[0]._links.verify.href
        #     and factorType == password
        #   when MFA_REQUIRED -> return

        auth2 = self.httpreq("https://inloggen.eneco.nl/api/v1/authn/factors/password/verify?rememberDevice=false", json.dumps( {"password":password,"stateToken":token}))
        if self.args.verbose:
            self.dump_auth_status(auth2)
        if auth2.get('status') == 'MFA_REQUIRED':
            if self.args.noninteractive:
                raise Exception("MFA_REQUIRED")
            factors = auth2.get("_embedded", {}).get("factors", [])
            auth3 = self.httpreq(factors.pop().get("_links").get("verify").get("href"), json.dumps({"passCode":"", "stateToken":token}))
            if self.args.verbose:
                self.dump_auth_status(auth3)
            code = input("Check your mail, enter MFA code:")
            auth2 = self.httpreq(auth3.get("_links").get("next").get("href"), json.dumps({"passCode":code, "stateToken":token}))
            if self.args.verbose:
                self.dump_auth_status(auth2)
        # check if status == SUCCESS
        if auth2.get('status') != 'SUCCESS':
            return

        #  get _links.next.href

        html2 = self.httpreq(f"https://inloggen.eneco.nl/login/step-up/redirect?stateToken={token}")

        self.auth = self.extractIdToken(html2)
        if not self.auth:
            print("WARNING: failed to get id-token")
            return

        # customerId is embedded in the token 
        self.customerid = self.extractCustomerIdFromToken(self.auth)

        # alternative: extract form in order to get customer-id
        #ehtml = self.httpreq("https://www.eneco.nl/mijn-eneco/")
        #self.customerid = self.extractCustomerId(ehtml)

        return True

        """
        note: 2023-07-13  /v1/enecoweb/v2 was changed to /dxpweb/nl
        /v1/enecoweb/eneco/customers/
        /v1/enecoweb/eneco/customers/<CUSTID>/preferences/contact
        /v1/enecoweb/eneco/customers/<MYNUM>/accounts/<CUSTID>/usages/monthSummary?year=<YEAR>&month=<MONTH>
        /v1/enecoweb/public/eneco/email/personaloffer
        /v1/enecoweb/public/eneco/preferences/contact?recipient=
        /v1/enecoweb/public/eneco/usages/mer?recipient=
        /v1/enecoweb/v2/eneco/customers/<CUSTID>/username
         ...<MYNUM>/accounts/<TVAL>/financials/preferences
         ...<MYNUM>/accounts/<TVAL>/products?includeproductrates=true
         ...<MYNUM>/accounts/<TVAL>/usages/energyreports
         ...<MYNUM>/accounts/<TVAL>/usages/mer
         ...<MYNUM>/documents/
         ...<MYNUM>/orders/
         ...<MYNUM>/password
         ...<MYNUM>/profile
         ...<MYNUM>/useraccount
        """

    def getprofile(self):
        return self.httpreq(f"{self.baseurl}/dxpweb/nl/eneco/customers/{self.customerid}/profile")
    def getinsights(self):
        return self.httpreq(f"{self.baseurl}/dxpweb/nl/eneco/customers/{self.customerid}/accounts/2/usages/services/insights")
    def getproducts(self):
        return self.httpreq(f"{self.baseurl}/dxpweb/nl/eneco/customers/{self.customerid}/accounts/2/products?includeproductrates=true")
    def getusage(self, start, per="Day", interval="Hour"):
        """
        This will return a json dict with data for 7 days from 'start'
{
  "data": {
    "metadata": { "interval": "Hour", "aggregation": "Week" },
    "usages": [
      {
        "period": { "from": "2022-09-15", "to": "2022-09-21" },
        "entries": [
           ...
        ],
        "summary": {
          "aggregationTotals": {
            "warmth": null,
            "gas": { ... },
            "electricity": { ... },
            "redelivery": null,
            "produced": null,
            "tapWater": null
          }
        }
      }
    ]
  }
}

Where each entry has the following:
{
"actual": {
  "date": "2022-09-21T23:00:00Z",
  "warmth": null,
  "gas": { ... },  -- measurement
  "electricity": { ... },  -- measurement
  "redelivery": null,
  "produced": null,
  "tapWater": null,
  "totalCostInclVat": 0,
  "totalUsageCostInclVat": 0,
  "totalFixedCostInclVat": 0
},
"previousYear": { ... },  -- same content as 'actual'
"budget": null,
"weather": null
}

each measurement has this:
{
  "status": "MEASURED",
  "isDoubleTariff": true,
  "isDoubleMeter": true,
  "collectorType": "P4",
  "high": 0,
  "highCostInclVat": 0,
  "totalUsageCostInclVat": 0.07,
  "low": 0.237250000000131,
  "lowCostInclVat": 0.06982030250003855,
  "fixedCostInclVat": -0.05,
  "totalCostInclVat": 0.02,
  "errorCodes": null
}
        """
        q = dict(
            aggregation = per,
            interval = interval,
            start = start,
            addBudget = True,
            addWeather = True,
            extrapolate = False
        )
        return self.httpreq(f"{self.baseurl}/dxpweb/nl/eneco/customers/{self.customerid}/accounts/2/usages?"+urllib.parse.urlencode(q))

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
    if not args.username and cfg.has_option('eneco', 'user'):
        args.username = cfg.get('eneco', 'user')
    if not args.password and cfg.has_option('eneco', 'pass'):
        args.password = cfg.get('eneco', 'pass')

def decode_datetime(t):
    return datetime.strptime(t, "%Y-%m-%d")

def main():
    import argparse
    parser = argparse.ArgumentParser(description='per uur gegevens van de mijn-eneco gebruiksgegevens')
    parser.add_argument('--debug', '-d', action='store_true', help=argparse.SUPPRESS) # 'print all intermediate steps'
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--profile', action='store_true', help='print gebruikers profiel')
    parser.add_argument('--insights', action='store_true', help='print insights gegevens')
    parser.add_argument('--products', action='store_true', help='print producten')
    parser.add_argument('--noninteractive', '-n', action='store_true', help='non interactive use - no prompts')
    parser.add_argument('--since', '--from', type=str, help='get usage from', metavar='DATE')
    parser.add_argument('--until', type=str, help='get usage until, default=now', metavar='DATE')
    parser.add_argument('--weeks', '-w', type=int, default=0, help='hoeveel weken')
    parser.add_argument('--username', '-u', type=str, help=argparse.SUPPRESS)
    parser.add_argument('--password', '-p', type=str, help=argparse.SUPPRESS)
    parser.add_argument('--config', help=argparse.SUPPRESS, default='~/.energierc') # 'specify configuration file.'
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

    en = Eneco(args)

    if not en.login(args.username, args.password):
        return

    if args.profile:
        j = en.getprofile()
        print(json.dumps(j))
        return
    elif args.insights:
        j = en.getinsights()
        print(json.dumps(j))
        return
    elif args.products:
        j = en.getproducts()
        print(json.dumps(j))
        return

    t0 = None
    t1 = datetime.now()
    td = timedelta(days=7)
    if args.since:
        t0 = decode_datetime(args.since)
    if args.until:
        t1 = decode_datetime(args.until)
    if args.weeks and args.since and args.until:
        print("You can specify only two out of weeks, since and until")
        return
    if t1 is None:
        t1 = t0 + td*args.weeks
    if t0 is None:
        t0 = t1 - td*args.weeks

    if t0==t1:
        print("nothing to do, specify nr of weeks(-w), or --from + --until")
        return
    t = t0
    while t < t1:
        j = en.getusage("%d-%d-%d" % (t.year, t.month, t.day), "Week", "Hour")
        print(json.dumps(j))
        t += td


if __name__ == '__main__':
    main()
