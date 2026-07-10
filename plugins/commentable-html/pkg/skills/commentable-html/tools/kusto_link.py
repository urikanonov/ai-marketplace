#!/usr/bin/env python3
"""Build a deterministic "Run in Azure Data Explorer" deep link for the Azure Data Explorer web UX.

A commentable report is static and self-contained, so an embedded KQL query cannot be run
in place. Instead, each query block carries an adjacent link that opens the query,
pre-loaded, in https://dataexplorer.azure.com against a chosen cluster + database.

Encoding (the same scheme the Kusto web UX uses for its share links):

    utf-8 query  ->  gzip (mtime pinned to 0)  ->  base64  ->  percent-encode  ->  ?query=

Pinning gzip mtime to 0 makes the output reproducible, so the same query always
yields the same link (stable diffs, testable). Percent-encoding the base64 keeps
the URL valid no matter how the consumer parses the query string (a raw '+' in a
query string is ambiguous - some parsers turn it into a space and corrupt the
payload).

CLI:
    python tools/kusto_link.py <cluster> <database> "<query>"
    python tools/kusto_link.py <cluster> <database>          # query on stdin

<cluster> may be a bare host (wcdprod.kusto.windows.net) or a full https URL; the
scheme and any trailing slash are stripped.
"""
import base64
import gzip
import io
import re
import sys
from urllib.parse import quote, urlsplit

_BASE = "https://dataexplorer.azure.com"

# A Kusto cluster is a plain DNS host (optionally with a port), e.g.
# "wcdprod.kusto.windows.net" or "m365dcogs.westus.kusto.windows.net". Anything
# outside this set (quotes, spaces, '/', '?', '#', '&', ...) must be rejected: the
# host is placed into the report's <a href="...">, so a stray quote would break the
# attribute and a stray '?'/'#' would corrupt the URL.
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?(?::[0-9]{1,5})?$")

# A generated link longer than this is likely to be rejected by browsers / tools
# (many cap URLs well below 32k); warn so the author trims or parameterizes.
_URL_WARN_LEN = 8192


def normalize_cluster(cluster):
    """Return the validated bare cluster host.

    Accepts a full ``https://host[/path]`` URL or a bare ``host[:port]`` (with an
    optional trailing slash), keeps only the host, and rejects anything that is not
    a plain DNS host - a value with quotes, spaces, or URL-structural characters
    would break the ``href`` it is embedded in, so it raises ``ValueError``.
    """
    c = (cluster or "").strip()
    if "://" in c:
        c = urlsplit(c).netloc  # a full URL's netloc excludes the path by definition
    else:
        c = c.rstrip("/")       # a bare host may carry an optional trailing slash
        if "/" in c:            # but an interior path segment is a typo, not a cluster
            raise ValueError("invalid cluster host (unexpected path segment): %r" % (cluster,))
    if not _HOST_RE.match(c):
        raise ValueError("invalid cluster host: %r" % (cluster,))
    if ":" in c:
        port = c.rsplit(":", 1)[1]
        if not (port.isdigit() and 1 <= int(port) <= 65535):
            raise ValueError("invalid cluster port (must be 1..65535): %r" % (cluster,))
    return c


def encode_query(query):
    """gzip (mtime 0) then base64 the query, returning ASCII base64 text.

    Line endings are normalized to LF first so the link does not depend on whether
    the query was authored/stored with CRLF or LF (a CRLF `.kql` file and the same
    query typed with LF produce the identical link).
    """
    normalized = query.replace("\r\n", "\n").replace("\r", "\n")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(normalized.encode("utf-8"))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def kusto_link(cluster, database, query):
    """Build the full dataexplorer.azure.com deep link that runs `query`."""
    host = normalize_cluster(cluster)
    if not (database or "").strip():
        raise ValueError("database is required")
    if not (query or "").strip():
        raise ValueError("query is required")
    payload = quote(encode_query(query), safe="")
    return "%s/clusters/%s/databases/%s?query=%s" % (
        _BASE, host, quote(database, safe=""), payload)


def main(argv):
    if len(argv) < 3 or len(argv) > 4:
        sys.stderr.write(
            "usage: python tools/kusto_link.py <cluster> <database> [query]\n"
            "       the query is read from stdin when the 3rd argument is omitted;\n"
            "       quote a multi-word query so it arrives as one argument.\n")
        return 2
    cluster, database = argv[1], argv[2]
    if len(argv) > 3:
        query = argv[3]
    else:
        # Read stdin as raw bytes and decode UTF-8 explicitly: sys.stdin.read()
        # would use the platform locale (cp1252 on Windows) and corrupt unicode.
        query = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    # A trailing newline (every .kql file has one) would change the payload, so the
    # arg form and the piped form of the same query yield different links - strip it.
    query = query.rstrip("\r\n")
    try:
        url = kusto_link(cluster, database, query)
    except ValueError as exc:
        sys.stderr.write("kusto_link: %s\n" % exc)
        return 2
    if len(url) > _URL_WARN_LEN:
        sys.stderr.write(
            "kusto_link: warning - generated URL is %d chars; it may exceed browser/tool "
            "limits. Trim or parameterize the query.\n" % len(url))
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
