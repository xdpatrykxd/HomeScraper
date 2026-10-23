"""Polish display names for structured source codes (not model-generated)."""

CODES = {
    'property_subtype': {
        'APARTMENT': 'mieszkanie', 'HOUSE': 'dom', 'GROUND_FLOOR': 'mieszkanie na parterze',
        'FLAT_STUDIO': 'kawalerka', 'DUPLEX': 'mieszkanie dwupoziomowe',
        'TRIPLEX': 'mieszkanie trzypoziomowe', 'PENTHOUSE': 'apartament na najwyższym piętrze',
        'LOFT': 'loft', 'VILLA': 'willa', 'BUNGALOW': 'dom parterowy',
        'TOWN_HOUSE': 'dom miejski', 'MANSION': 'rezydencja', 'COUNTRY_COTTAGE': 'dom wiejski',
        'CHALET': 'chata', 'FARMHOUSE': 'dom gospodarstwa', 'EXCEPTIONAL_PROPERTY': 'nieruchomość nietypowa',
        'MIXED_USE_BUILDING': 'budynek mieszkalno-usługowy', 'OTHER_PROPERTY': 'inna nieruchomość',
    },
    'building_condition': {'GOOD': 'dobry', 'AS_NEW': 'jak nowy', 'JUST_RENOVATED': 'po remoncie',
                           'TO_RENOVATE': 'do remontu', 'TO_RESTORE': 'do odrestaurowania',
                           'TO_BE_DONE_UP': 'do odświeżenia'},
    'heating_type': {'GAS': 'gaz', 'FUELOIL': 'olej opałowy', 'ELECTRIC': 'elektryczne',
                    'ELECTRICITY': 'elektryczne', 'WOOD': 'drewno', 'PELLET': 'pellet',
                    'SOLAR': 'słoneczne', 'HEAT_PUMP': 'pompa ciepła', 'COAL': 'węgiel'},
    'kitchen_type': {'NOT_INSTALLED': 'niezainstalowana', 'INSTALLED': 'zainstalowana',
                    'SEMI_EQUIPPED': 'częściowo wyposażona', 'USA_INSTALLED': 'otwarta, zainstalowana',
                    'USA_SEMI_EQUIPPED': 'otwarta, częściowo wyposażona',
                    'HYPER_EQUIPPED': 'w pełni wyposażona', 'USA_HYPER_EQUIPPED': 'otwarta, w pełni wyposażona'},
    'flood_zone': {'NON_FLOOD_ZONE': 'poza strefą powodziową', 'POSSIBLE_FLOOD_ZONE': 'możliwe zagrożenie powodziowe',
                   'RECOGNIZED_FLOOD_ZONE': 'strefa powodziowa', 'FLOOD_ZONE': 'strefa powodziowa',
                   'POSSIBLE_N_CIRCUMSCRIBED_WATERSIDE_ZONE': 'możliwa strefa powodziowa i wydzielona strefa nadrzeczna',
                   'RECOGNIZED_N_CIRCUMSCRIBED_FLOOD_ZONE': 'strefa powodziowa i wydzielona strefa zalewowa'},
    'region': {'FLANDERS': 'Flandria', 'WALLONIA': 'Walonia', 'BRUSSELS': 'Bruksela'},
}
ORIENTATIONS = {'NORTH': 'północ', 'SOUTH': 'południe', 'EAST': 'wschód', 'WEST': 'zachód',
                'NORTH_EAST': 'północny wschód', 'NORTH_WEST': 'północny zachód',
                'SOUTH_EAST': 'południowy wschód', 'SOUTH_WEST': 'południowy zachód'}


def polish_code(field, value):
    code = value.upper()
    if field in {'garden_orientation', 'terrace_orientation'}:
        return ORIENTATIONS.get(code)
    if field in {'flood_p_score', 'flood_g_score'}:
        return value
    if field in {'province', 'district'}:
        return 'Antwerpia' if code == 'ANTWERP' else value
    return CODES.get(field, {}).get(code)
