# vim: set fileencoding=utf-8 : 

"""names.py: Functions for working with vernacular names."""

import logging
import json

from nomdb import config, common, languages
import access

# There are only two use-cases for vernacular name retrieval:
# 1. /edit, which needs every possible name in every possible language with higher taxonomy.
#   get_detailed_vname(scname, ...) -> dict[vnames]
# 2. The currently accepted name in the standard languages for a set of names.
#   get_vname(scnames, ...) -> dict[vnames]
# and hey, because polymorphism is great, right
#   get_vname(scname, ...) -> vname
#
# In theory, we could make things faster by looking up scientific names within a dataset directly,
# but in practice we don't do that often. Maybe if I write it, they will come?

def get_vname(scname):
    return get_detailed_vname(scname)

def get_vnames(list_scnames):
    """

    :param scnames: list[str]
    :return: dict
    """

    # Set up results and names to query.
    final_results = dict()
    scnames = list(set(list_scnames))

    # Prepare a list of languages to use.
    languages_str = ", ".join(map(lambda lang: "'" + lang.lower() + "'", languages.language_names_list))

    # We go through names in chunks, so we don't overwhelm CartoDB on long queries.
    for i in xrange(0, len(scnames), config.SEARCH_CHUNK_SIZE):
        chunk_scnames = scnames[i:i+config.SEARCH_CHUNK_SIZE]

        # Turn them into a search string.
        set_scnames = set(chunk_scnames)

        # We might also want to search for genus names.
        for name in chunk_scnames:
            pieces = name.split()
            if len(pieces) > 1:
                set_scnames.add(pieces[0].lower())

        # print("DEBUG: vnames = " + ', '.join(set_scnames))

        scnames_str = ", ".join(set(
            map(lambda name: "(" + common.encode_b64_for_psql(name.lower()) + ")", set_scnames)
        ))

        sql = """
            SELECT DISTINCT
                qname,
                LOWER(scname) AS scname_lc,
                LOWER(lang) AS lang_lc,
                FIRST_VALUE(cmname) OVER best_match AS cmname,
                FIRST_VALUE(source) OVER best_match AS source,
                FIRST_VALUE(source_priority) OVER best_match AS source_priority,
                FIRST_VALUE(url) OVER best_match AS url,
                FIRST_VALUE(source_url) OVER best_match AS source_url,
                FIRST_VALUE(updated_at) OVER best_match AS updated_at
            FROM %s vnames
                RIGHT JOIN (SELECT NULL AS qname UNION VALUES %s) qn
                    ON LOWER(scname) = qname
            WHERE
                qname IS NOT NULL AND (
                    cmname IS NULL OR
                    LOWER(lang) IN (%s)
                )
            WINDOW best_match AS (
                PARTITION BY LOWER(scname), lang ORDER BY
                    source_priority DESC,
                    updated_at DESC
            )
            ORDER BY
                qname ASC,
                scname_lc ASC,
                cmname ASC
        """
        sql_query = sql.strip() % (
            access.ALL_NAMES_TABLE,
            scnames_str,
            languages_str
        )

        # print("Sql = <<" + sql_query + ">>")
        # print("URL = <<" + access.CDB_URL % ( urllib.urlencode(dict(q=sql_query))) + ">>")

        urlresponse = common.url_post(access.CDB_URL, {'q': sql_query})

        if urlresponse.status_code != 200:
            raise IOError("Could not read from CartoDB: " + str(urlresponse.status_code) + ": " + str(urlresponse.content))

        results = json.loads(urlresponse.content)
        rows_by_scname = common.group_by(results['rows'], 'qname')

        # Map qnames back to scnames
        for scname in chunk_scnames:
            final_results[scname] = dict()

            try:
                rows_by_lang = common.group_by(rows_by_scname[scname.lower()], 'lang_lc')
            except KeyError:
                # This only gets triggered if we have a vname for 'scname', but
                # not as one of the requested languages.
                for lang in languages.language_names_list:
                    final_results[scname][lang] = None

                continue

            for lang in languages.language_names_list:
                if lang not in rows_by_lang:
                    final_results[scname][lang] = None
                    continue

                rows = rows_by_lang[lang]

                # There should only be one row!
                if len(rows) != 1:
                    raise RuntimeError(
                        "SQL query should only return one row per scientific name, but we have %d of '%s'@%s" % (
                            len(rows),
                            scname,
                            lang
                        )
                    )

                # ... but it might be blank.
                result = rows[0]

                if result['cmname'] is None:
                    # Maybe we have a genus match?
                    pieces = scname.split()
                    if len(pieces) > 1 and len(rows_by_scname[pieces[0].lower()]) == 1:
                        result = rows_by_scname[pieces[0].lower()][0]
                    else:
                        final_results[scname][lang] = None
                        continue

                final_results[scname][lang] = VernacularName(
                    scname,
                    result['qname'],
                    result['lang_lc'],
                    result['cmname'],
                    result['source'],
                    result['source_priority'] if result['source_priority'] is not None else config.PRIORITY_DEFAULT,
                    result['url'],
                    result['source_url'],
                    result['updated_at']
                )

    return final_results

def get_detailed_vname(scname):
    raise RuntimeError("Not implemented")

#
# CLASS VernacularName
#
class VernacularName:
    """ Stores a single vernacular name in a particular language. """
    def __init__(self, scientific_name, matched_name, lang, vernacular_name, source, source_priority, url, source_url, updated_at):
        """ Create a VernacularName
        
        :param scientific_name: The scientific name that was queried (not necessarily the one that was matched!)
        :param matched_name: The name the vernacular_name corresponds to.
        :param lang: The language code ('en', 'zh-Hans', etc.)
        :param vernacular_name: The vernacular name retrieved.
        :param source_priority: The source priority of the match.
        :param source: The source that was matched.
        :return:
        """
        self.scname = scientific_name
        self.matched_name = matched_name
        self.lang = lang
        self.cmname = vernacular_name
        self.source = source
        self.source_priority = int(source_priority)
        if not(config.PRIORITY_MIN <= self.source_priority <= config.PRIORITY_MAX):
            self.source_priority = config.PRIORITY_DEFAULT
        self.url = url
        self.source_url = source_url
        self.updated_at = updated_at

    def __repr__(self):
        """For debugging and the like."""
        return "<'%s'@%s>" % (
            self.cmname,
            self.lang
        )

    @property
    def scientific_name(self):
        return self.scname

    @property
    def matched_name(self):
        return self.matched_name

    @property
    def lang(self):
        return self.lang

    @property
    def vernacular_name(self):
        return self.cmname

    @property
    def vernacular_name_formatted(self):
        return common.format_name(self.cmname) if self.cmname is not None else None

    @property
    def source_priority(self):
        return self.source_priority

    @property
    def source(self):
        return self.source

    @property
    def url(self):
        return self.url

    @property
    def source_url(self):
        return self.source_url

    @property
    def updated_at(self):
        return self.updated_at