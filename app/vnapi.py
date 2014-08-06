# vim: set fileencoding=utf-8 : 

# vnapi.py
# An API for communicating with the Vernacular Name system
# on CartoDB.

from google.appengine.api import urlfetch

import json
import urllib

# Authentication
import access

# Configuration
DEADLINE_FETCH = 60 # seconds to wait during URL fetch

def url_get(url):
    return urlfetch.fetch(url, deadline = DEADLINE_FETCH)

def sortNames(rows):
    result_table = dict()                                                   
        
    for row in rows:                                             
        lang = row['lang']                                                  

        if not lang in result_table:                                        
            result_table[lang] = []                                         

        result_table[lang].append(row['cmname'] + " [" + row['source_priority'] + "]")

    return result_table 


def getVernacularNames(name):
    # TODO: sanitize input                                                  
    sql = "SELECT DISTINCT lang, cmname, source_priority FROM %s WHERE scname = '%s' ORDER BY source_priority ASC"
    response = url_get(access.CDB_URL % urllib.urlencode(
        dict(q = sql % (access.ALL_NAMES_TABLE, name))
    ))

    if response.status_code != 200:                                         
        raise "Could not read server response: " + response.content

    results = json.loads(response.content)                                  
    return sortNames(results['rows'])

def searchForName(name):
    # TODO: sanitize input                                                  

    # Escape any characters that might be used in a LIKE pattern            
    # From http://www.postgresql.org/docs/9.1/static/functions-matching.html
    search_pattern = name.replace("_", "__").replace("%", "%%")             

    sql = "SELECT DISTINCT scname, cmname FROM %s WHERE scname LIKE '%%%s%%' OR cmname LIKE '%%%s%%' ORDER BY scname ASC"
    return url_get(access.CDB_URL % urllib.urlencode(
        dict(q = sql % (
            access.ALL_NAMES_TABLE, name, name                                    
        ))))
