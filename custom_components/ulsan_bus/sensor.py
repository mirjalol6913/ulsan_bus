import logging
import requests
import math
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from datetime import timedelta
from datetime import datetime

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (CONF_NAME, CONF_API_KEY, CONF_ICON)
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

REQUIREMENTS = ['xmltodict==0.12.0']

_LOGGER = logging.getLogger(__name__)

CONF_API_ISSUED_DATE = 'api_issued_date'

CONF_STATIONS   = 'stations'
CONF_STATION_ID = 'station_id'
CONF_STATION_UPDATE_TIME = 'update_time'
CONF_START_TIME = 'start_time'
CONF_END_TIME   = 'end_time'
CONF_BUS_ID = 'bus_id'

ULSAN_BUS_API_URL = 'http://openapi.its.ulsan.kr/UlsanAPI/getBusArrivalInfo.xo?stopid={}&pageNo=1&numOfRows=100&type=json\&serviceKey={}'

_BUS_PROPERTIES = {
    'busRouteId': '노선ID',
    'rtNm': '버스번호',
    'arrTime': '도작예정시간',
    'isUpdate': 'is Update'
}

DEFAULT_NAME = 'Ulsan Bus'
DEFAULT_STATION_NAME = '삼호교'

# default icon
ICON_STATION      = 'mdi:nature-people'
ICON_BUS          = 'mdi:bus'
ICON_BUS_READY    = 'mdi:bus-clock'
ICON_BUS_ALERT    = 'mdi:bus-alert'

ICON_SIGN_CAUTION = 'mdi:sign-caution'
ICON_EYE_OFF      = 'mdi:eye-off'

# default_time
DEFAULT_START_HOUR = 5
DEFAULT_END_HOUR   = 24

# update time
MIN_TIME_BETWEEN_API_UPDATES    = timedelta(seconds=120) 

MIN_TIME_BETWEEN_API_SENSOR_UPDATES = timedelta(seconds=3600)

MIN_TIME_BETWEEN_STATION_SENSOR_UPDATES = timedelta(seconds=90) 
MIN_TIME_BETWEEN_BUS_SENSOR_UPDATES = timedelta(seconds=10)

# attribute value
ATTR_ROUTE_ID = 'busRouteId'

PLATFORM_SCHEMA = PLATFORM.SCHEMA.extend({
    vol.Required(CONF_API_KEY): cv.string,
    vol.Optional(CONF_API_ISSUED_DATE): cv.string,
    vol.Required(CONF_STATIONS): vol.All(cv.ensure_list, [{
        vol.Required(CONF_STATION_ID): cv.string,
        vol.Optional(CONF_NAME, default = DEFAULT_STATION_NAME): cv.string,
        vol.Optional(CONF_STATION_UPDATE_TIME, default=[]): vol.All(cv.ensure_list, [{
            vol.Required(CONF_START_TIME, default = ''): cv.string,
            vol.Required(CONF_END_TIME, default =''): cv.string,
        }])
    }])
})

def isBetweenNowTime(start, end):
    rtn = False

    now  = datetime.now()
    year = now.year
    mon  = now.month
    day  = now.day
    hour = now.hour
    min  = now.minute

    nowTime = datetime(year, mon, day, hour, min)

    try:
        arrTm1 = start.split(":")
        arrTm2 = end.split(":")

        st  = datetime(year, mon, day, int(arrTm1[0]), int(arrTm1[1]))
        ed  = datetime(year, mon, day, int(arrTm2[0]), int(arrTm2[1]))

        if nowTime >= st and nowTime <= ed:
            rtn = True
        else:
            rtn = False
    except Excption as ex:
        _LOGGER.error('Failed to isBetweenNowTime() Seoul Bus Method Error: %s', ex)

    return rtn

def second2min(val):
    try:
        if 60 >  int(val):
            return '{}초'.format(val)
        else:
            min = math.floor(int(val)/60)
            sec = int(val)%60
            return '{}분{}초'.format(str(min), str(sec))
    except Exception as ex:
        _LOGGER.error('Failed to second2min() Seoul Bus Method Error: %s', ex)

    return val

def cover_list(dict):
    if not dict:
        return []
    elif isinstance(dict, list):
        return dict
    else:
        return [dict]

def setup_platform(hass, config, add_entities, discovery_info=None):
    name = config.get(CONF_NAME)
    api_key         = config.get(CONF_API_KEY)
    api_issued_date = config.get(CONF_API_ISSUED_DATE)
    stations        = config.get(CONF_STATIONS)
    
    sensors = []
    
    for station in stations:
        api = UlsanBusAPI(api_key, station[CONF_STATION_ID], station[CONF_STATION_UPDATE_TIME])
        
        sensor = BusStationSensor(station[CONF_STATION_ID], station[CONF_NAME], station[CONF_STATION_UPDATE_TIME], api)
        
        sensor.update()
        sensors += [sensor]
        
        for bus_id, value in sensor.buses.items():
            try:
                sensors += [BusSensor(station[CONF_STATION_ID], station[CONF_NAME], station[CONF_STATION_UPDATE_TIME], bus_id, value.get(CONF_NAME, ''), value, api)]
            except Exception as ex:
                _LOGGER.error('[Ulsan Bus] Failed to BusSensor add  Error: %s', ex)

    add_entities(sensors, True)

    
    
    
class UlsanBusAPI:
    """Ulsan Bus API."""
    def __init__(self, api_key, station_id, update_time):
        """Initialize the Ulsan Bus API."""
        self._api_key = api_key
        self._station_id  = station_id
        self._update_time = update_time
        self._isUpdate  = True

        self._isError   = False
        self._errorCd   = None
        self._errorMsg  = None

        
        self._sync_date = None
        self.result = {}

    def update(self):
        """Update function for updating api information."""
        dt = datetime.now()
        syncDate = dt.strftime("%Y-%m-%d %H:%M:%S")

        self._sync_date = syncDate

        if dt.hour > DEFAULT_START_HOUR and dt.hour < DEFAULT_END_HOUR:
            self._isUpdate = True
        else:
            self._isUpdate = False

        if len(self._update_time) > 0:
            for item in self._update_time:
                stt_tm = item['start_time']
                end_tm = item['end_time']

            self._isUpdate = isBetweenNowTime(stt_tm, end_tm)

        import xmltodict
        try:
            url = ULSAN_BUS_API_URL.format(self._station_id, self._api_key)

            response = requests.get(url, timeout=10)
            response.raise_for_status()

            page = response.content.decode('utf8')

            hdr = xmltodict.parse(page)['tableinfo']

            bus_dict = {}

            if ( hdr['resultCode'] != '0'):
                self._isError = True

                self._errorCd = hdr['resultCode']
                self._errorMsg = hdr['Msg']

                _LOGGER.error('Failed to update Ulsan Bus API status Error: %s', hdr['headerMsg'] )
            else:
                self._isError = False
                self._errorCd = None
                self._errorMsg = None

                rows = xmltodict.parse(page)['tableInfo']['list']['row']

                for row in cover_list(rows):
                    bus_dict[row['ATTR_ROUTE_ID']] = {
                        'rtNm': row['ROUTENM'],
                        'busRouteId': row['ROUTEID'],
                        'arrTime': row['ARRIVALTIME']
                        
                        'syncDate': syncDate,
                        'isUpdate': self._isUpdate
                    }

            self.result = bus_dict
            #_LOGGER.debug('Seoul Bus API Request Result: %s', self.result)
        except Exception as ex:
            _LOGGER.error('Failed to update Ulsan Bus API status Error: %s', ex)
            raise

class BusStationSensor(Entity):
    def __init__(self, id, name, update_time, api):
        self._station_id = id
        self._station_name = name
        self._update_time   = update_time
        self._isUpdate = None
        self._stt_time = None
        self._end_time = None

        self._sync_date = None

        self._api   = api
        self._icon  = ICON_STATION
        self._state = None
        self.buses  = {}

    @property
    def entity_id(self):
        """Return the entity ID."""
        return 'sensor.ulsan_bus_s{}'.format(self._station_id)

    @property
    def name(self):
        """Return the name of the sensor, if any."""
        if not self._station_name:
            return 'St.{}'.format(self._station_id)
        return '{}({})'.format(self._station_name, self._station_id)

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        if self._api._isError:
            return ICON_SIGN_CAUTION

        if not self._isUpdate:
            return ICON_EYE_OFF

        if not self._api._isUpdate:
            return ICON_EYE_OFF

        return self._icon

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._api._isError:
            return 'Error'

        if not self._isUpdate:
            return '-'

        if not self._isUpdate:
            return '-'

       

    @Throttle(MIN_TIME_BETWEEN_STATION_SENSOR_UPDATES)
    def update(self):
        """Get the latest state of the sensor."""
        if self._api is None:
            return

        if self._isUpdate is None:
            self._api.update()

        dt = datetime.now()
        syncDate = dt.strftime("%Y-%m-%d %H:%M:%S")

        self._sync_date = syncDate

        if len(self._update_time) > 0:
            stt_tm = None
            end_tm = None

            for item in self._update_time:
                stt_tm = item['start_time']
                end_tm = item['end_time']

                self._stt_time = stt_tm
                self._end_time = end_tm

            self._isUpdate = isBetweenNowTime(stt_tm, end_tm)

        if self._isUpdate:
            self._api.update()

        buses_dict = self._api.result

        

    @property
    def device_state_attributes(self):
        """Attributes."""
        attr = {}

        # API Error Contents Attributes Add
        if self._api._isError :
            attr['API Error Code'] = self._api._errorCd
            attr['API Error Msg'] = self._api._errorMsg

        for key in sorted(self.buses):
            attr['{} '.format(self.buses[key].get('rtNm', key))] = '{} {}'.format(self.buses[key].get('arrTime', '0'), '초') ) 

        attr['Sync Date'] = self._sync_date
        attr['is Update'] = self._isUpdate
        attr['start time'] = self._stt_time
        attr['end time']   = self._end_time

        return attr

class BusSensor(Entity):
    def __init__(self, station_id, station_name, station_update_time, bus_id, bus_name, values,  api):
        self._station_id   = station_id
        self._station_name = station_name
        self._station_update_time = station_update_time
        self._bus_id   = bus_id
        self._bus_name = bus_name

        self._isUpdate = None
        self._stt_time = None
        self._end_time = None

        self._api = api
        self._state = None
        self._data  = {}

        
        self._rtNm = values['ROUTENM']
        self.arrTime = values['ARRIVALTIME']
        
        

    @property
    def entity_id(self):
        """Return the entity ID."""
        return 'sensor.ulsan_bus_{}_{}'.format(self._station_id, self._bus_id)

    @property
    def name(self):
        """Return the name of the sensor, if any."""
        station_name = self._station_name

        if not self._station_name:
            station_name = 'St.{}'.format(self._station_id)

        if not self._bus_name:
            return '{} {}'.format(station_name, self._rtNm)

        return self._bus_name

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        if not self._isUpdate:
            return ICON_BUS_READY

        

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        if not self._isUpdate:
            return ''

        return ''

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self._isUpdate:
            return '-'
        else:
            return '0' if self._data['arrTime'] == '0' else second2min(self._data['arrTime'])

        return '-'

    @Throttle(MIN_TIME_BETWEEN_BUS_SENSOR_UPDATES)
    def update(self):
        """Get the latest state of the sensor."""
        if self._api is None:
            return

        dt = datetime.now()
        syncDate = dt.strftime("%Y-%m-%d %H:%M:%S")

        self._sync_date = syncDate


        if len(self._station_update_time) > 0:
            stt_tm = None
            end_tm = None

            for item in self._station_update_time:
                stt_tm = item['start_time']
                end_tm = item['end_time']

                self._stt_time = stt_tm
                self._end_time = end_tm

            self._isUpdate = isBetweenNowTime(stt_tm, end_tm)

        buses_dict = self._api.result
        self._data = buses_dict.get(self._bus_id,{})

       

    @property
    def device_state_attributes(self):
        """Attributes."""
        attr = {}

        for key in self._data:
           attr[_BUS_PROPERTIES[key]] = self._data[key]

        attr[_BUS_PROPERTIES['syncDate']] = self._sync_date

        attr[_BUS_PROPERTIES['isUpdate']]   = self._isUpdate
        attr[_BUS_PROPERTIES['start_time']] = self._stt_time
        attr[_BUS_PROPERTIES['end_time']]   = self._end_time

        return attr
