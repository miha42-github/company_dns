from . import edgar
from . import wikipedia
from geopy.geocoders import ArcGIS


class Query:
    def __init__(self):
        self.locator = ArcGIS (timeout=2)

    def locate (self, place):
        l = self.locator.geocode (place)
        return l.longitude, l.latitude, l.address