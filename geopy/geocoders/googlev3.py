"""
:class:`.GoogleV3` is the Google Maps V3 geocoder.
"""

import base64
import hashlib
import hmac
from urllib import urlencode
from urllib2 import urlopen

from geopy.compat import json
from geopy.point import Point

from geopy.geocoders.base import Geocoder, GeocoderResultError
from geopy.util import logger, decode_page


class GoogleV3(Geocoder):
    """
    Geocoder using the Google Maps v3 API. Documentation at:
        https://developers.google.com/maps/documentation/geocoding/
    """

    def __init__(self, domain='maps.googleapis.com', protocol='http',
                 client_id=None, secret_key=None, proxies=None):
        """
        Initialize a customized Google geocoder.

        API authentication is only required for Google Maps Premier customers.

        :param string domain: should be the localized Google Maps domain to
            connect to. The default is 'maps.google.com', but if you're
            geocoding address in the UK (for example), you may want to set it
            to 'maps.google.co.uk' to properly bias results.

        :param string protocol: http or https.

        :param string client_id: If using premier, the account client id.

        :param string secret_key: If using premier, the account secret key.
        """
        super(GoogleV3, self).__init__(proxies=proxies)

        if protocol not in ('http', 'https'):
            raise ValueError('Supported protocols are http and https.')
        if client_id and not secret_key:
            raise ValueError('Must provide secret_key with client_id.')
        if secret_key and not client_id:
            raise ValueError('Must provide client_id with secret_key.')

        self.domain = domain.strip('/')
        self.protocol = protocol
        self.doc = {}

        if client_id and secret_key:
            self.premier = True
            self.client_id = client_id
            self.secret_key = secret_key
        else:
            self.premier = False
            self.client_id = None
            self.secret_key = None

    def _get_url(self, params):
        '''Returns a standard geocoding api url.'''
        return 'http://%(domain)s/maps/api/geocode/json?%(params)s' % (
            {'domain': self.domain, 'params': urlencode(params)})

    def _get_signed_url(self, params):
        '''Returns a Premier account signed url.'''
        params['client'] = self.client_id
        url_params = {
            'protocol': self.protocol,
            'domain': self.domain,
            'params': urlencode(params)
        }
        secret = base64.urlsafe_b64decode(self.secret_key)
        url_params['url_part'] = (
            '/maps/api/geocode/json?%(params)s' % url_params
        )
        signature = hmac.new(secret, url_params['url_part'], hashlib.sha1)
        url_params['signature'] = base64.urlsafe_b64encode(signature.digest())

        return ('%(protocol)s://%(domain)s%(url_part)s'
                '&signature=%(signature)s' % url_params)

    def geocode_url(self, url, exactly_one=True):
        '''Fetches the url and returns the result.'''
        logger.debug("%s.geocode_url: %s", self.__class__.__name__, url)
        return self.parse_json(self.urlopen(url), exactly_one)

    def geocode(self, query, bounds=None, region=None, # pylint: disable=W0221,R0913
                language=None, sensor=False, exactly_one=True):
        """
        Geocode a location query.

        :param string query: The address or query you wish to geocode.

        :param bounds: The bounding box of the viewport within which
            to bias geocode results more prominently.
        :type bounds: list or tuple

        :param string region: The region code, specified as a ccTLD
            ("top-level domain") two-character value.

        :param string language: The language in which to return results.
            Default None.

        :param bool sensor: Whether the geocoding request comes from a
            device with a location sensor. Default False.

        :param bool exactly_one: Return one result or a list of results, if
            available.
        """
        super(GoogleV3, self).geocode(query)

        params = {
            'address': self.format_string % query,
            'sensor': str(sensor).lower()
        }
        if bounds:
            params['bounds'] = bounds
        if region:
            params['region'] = region
        if language:
            params['language'] = language

        if not self.premier:
            url = self._get_url(params)
        else:
            url = self._get_signed_url(params)

        logger.debug("%s.geocode: %s", self.__class__.__name__, url)
        return self.geocode_url(url, exactly_one)

    def reverse(self, point, language=None, # pylint: disable=W0221
                    sensor=False, exactly_one=False):
        """
        Given a point, find an address.

        :param point: The coordinates for which you wish to obtain the
            closest human-readable addresses.
        :type point: :class:`geopy.point.Point`, list or tuple of (latitude,
            longitude), or string as "%(latitude)s, %(longitude)s"

        :param string language: The language in which to return results.
            Default None.

        :param boolean sensor: Whether the geocoding request comes from a
            device with a location sensor. Default False.

        :param boolean exactly_one: Return one result or a list of results, if
            available.
        """
        params = {
            'latlng': self._coerce_point_to_string(point),
            'sensor': str(sensor).lower()
        }
        if language:
            params['language'] = language

        if not self.premier:
            url = self._get_url(params)
        else:
            url = self._get_signed_url(params)

        logger.debug("%s.reverse: %s", self.__class__.__name__, url)
        return self.geocode_url(url, exactly_one)

    def parse_json(self, page, exactly_one=True):
        '''Returns location, (latitude, longitude) from json feed.'''
        if not isinstance(page, basestring):
            page = decode_page(page)
        self.doc = json.loads(page)
        places = self.doc.get('results', [])

        if not places:
            self._check_status(self.doc.get('status'))
            return None

        def parse_place(place):
            '''Get the location, lat, lng from a single json place.'''
            location = place.get('formatted_address')
            latitude = place['geometry']['location']['lat']
            longitude = place['geometry']['location']['lng']
            return (location, (latitude, longitude))

        if exactly_one:
            return parse_place(places[0])
        else:
            return [parse_place(place) for place in places]

    @staticmethod
    def _coerce_point_to_string(point):
        """
        Do the right thing on "point" input.
        """
        if isinstance(point, Point):
            point = ",".join(point.latitude, point.longitude)
        elif isinstance(point, (list, tuple)):
            point = ",".join(point[0], point[1])
        # else assume string
        return point

    @staticmethod
    def _check_status(status):
        '''Validates error statuses.'''
        if status == 'ZERO_RESULTS':
            raise GQueryError(
                'The geocode was successful but returned no results. This may'
                ' occur if the geocode was passed a non-existent address or a'
                ' latlng in a remote location.'
            )
        elif status == 'OVER_QUERY_LIMIT':
            raise GTooManyQueriesError(
                'The given key has gone over the requests limit in the 24'
                ' hour period or has submitted too many requests in too'
                ' short a period of time.'
            )
        elif status == 'REQUEST_DENIED':
            raise GQueryError(
                'Your request was denied, probably because of lack of a'
                ' sensor parameter.'
            )
        elif status == 'INVALID_REQUEST':
            raise GQueryError('Probably missing address or latlng.')
        else:
            raise GeocoderResultError('Unknown error.')


class GQueryError(GeocoderResultError):
    '''Generic Google query error.'''
    pass

class GTooManyQueriesError(GeocoderResultError):
    '''Raised when the query rate limit is hit.'''
    pass
