energy monitoring
=================

Some tools for monitoring your energy usage.

eneco.py and vattenfall.py
---------------

Tools which extract the hourly usage as recorded by Eneco or Vattenfall.

summarizeeneco.py and summarizevatten.py
---------------

Tools which summarize the output from the above tools.


configuration
---------------

configuration is stored in ~/.energierc

    [eneco]
    user=itsme@xs4all.nl
    pass=xyz

    [vattenfall]
    auth=The-Authorization-header-content
    customerid=<customerid>/<contractid>

For the eneco tool you can specify the username + password of your account in the config file.
For vattenfall it is a bit more complicated, as I have not yet implemented the full auth protocol.
You will have to extract the Authorization header manually using the debug mode of your webbrowser.
you will also need the customerid, This is composed of two numbers:
  * BusinessPartnerId
  * ContractAccountId
You can find these in response of either of these two urls:
  * https://api.vattenfall.nl/api/mijnnuonprd/v2/initialisation/....
  * https://api.vattenfall.nl/featuresprd/api/v1/messages?businessPartnerId=....


TODO
----

 * implement vattenfall authentication
 * merge the summarize tools into the eneco and vattenfall tools.
 * get the apikeys from their respective locations, instead of hardcoding them in my tools.

Author
------

Willem Hengeveld <itsme@xs4all.nl>

