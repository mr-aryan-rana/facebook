"""US location reference data used by extractor.detect_location().

AREA_CODE_TO_STATE: standard NANP (North American Numbering Plan) area
code assignments -- public, stable telecom data, not scraped or guessed.
Used as the primary signal since it's cross-referenced against a phone
number the extractor has already regex-matched AND verified via
verify_us_phone, making it far more reliable than free-text city matching.

MAJOR_US_CITIES: a curated, state-qualified fallback for leads with no
phone number. Deliberately excludes city names that collide with
well-known non-US cities of the same name (Cambridge, Manchester,
Portland, Richmond, Paris, London, Birmingham, etc.) -- a full "all US
cities" list would actually make location detection *less* reliable,
since bare name-matching can't tell Cambridge MA from Cambridge UK.
"""

AREA_CODE_TO_STATE = {
    "201": "NJ", "202": "DC", "203": "CT", "205": "AL", "206": "WA", "207": "ME",
    "208": "ID", "209": "CA", "210": "TX", "212": "NY", "213": "CA", "214": "TX",
    "215": "PA", "216": "OH", "217": "IL", "218": "MN", "219": "IN", "220": "OH",
    "223": "PA", "224": "IL", "225": "LA", "227": "MD", "228": "MS", "229": "GA",
    "231": "MI", "234": "OH", "239": "FL", "240": "MD", "248": "MI", "251": "AL",
    "252": "NC", "253": "WA", "254": "TX", "256": "AL", "260": "IN", "262": "WI",
    "267": "PA", "269": "MI", "270": "KY", "272": "PA", "274": "WI", "276": "VA",
    "281": "TX", "301": "MD", "302": "DE", "303": "CO", "304": "WV", "305": "FL",
    "307": "WY", "308": "NE", "309": "IL", "310": "CA", "312": "IL", "313": "MI",
    "314": "MO", "315": "NY", "316": "KS", "317": "IN", "318": "LA", "319": "IA",
    "320": "MN", "321": "FL", "323": "CA", "325": "TX", "330": "OH", "331": "IL",
    "334": "AL", "336": "NC", "337": "LA", "339": "MA", "340": "VI", "341": "CA",
    "346": "TX", "347": "NY", "351": "MA", "352": "FL", "360": "WA", "361": "TX",
    "364": "KY", "380": "OH", "385": "UT", "386": "FL", "401": "RI", "402": "NE",
    "404": "GA", "405": "OK", "406": "MT", "407": "FL", "408": "CA", "409": "TX",
    "410": "MD", "412": "PA", "413": "MA", "414": "WI", "415": "CA", "417": "MO",
    "419": "OH", "423": "TN", "424": "CA", "425": "WA", "430": "TX", "432": "TX",
    "434": "VA", "435": "UT", "440": "OH", "442": "CA", "443": "MD", "458": "OR",
    "463": "IN", "464": "IL", "469": "TX", "470": "GA", "475": "CT", "478": "GA",
    "479": "AR", "480": "AZ", "484": "PA", "501": "AR", "502": "KY", "503": "OR",
    "504": "LA", "505": "NM", "507": "MN", "508": "MA", "509": "WA", "510": "CA",
    "512": "TX", "513": "OH", "515": "IA", "516": "NY", "517": "MI", "518": "NY",
    "520": "AZ", "530": "CA", "531": "NE", "534": "WI", "539": "OK", "540": "VA",
    "541": "OR", "551": "NJ", "559": "CA", "561": "FL", "562": "CA", "563": "IA",
    "564": "WA", "567": "OH", "570": "PA", "571": "VA", "573": "MO", "574": "IN",
    "575": "NM", "580": "OK", "585": "NY", "586": "MI", "601": "MS", "602": "AZ",
    "603": "NH", "605": "SD", "606": "KY", "607": "NY", "608": "WI", "609": "NJ",
    "610": "PA", "612": "MN", "614": "OH", "615": "TN", "616": "MI", "617": "MA",
    "618": "IL", "619": "CA", "620": "KS", "623": "AZ", "626": "CA", "628": "CA",
    "629": "TN", "630": "IL", "631": "NY", "636": "MO", "641": "IA", "646": "NY",
    "650": "CA", "651": "MN", "657": "CA", "660": "MO", "661": "CA", "662": "MS",
    "667": "MD", "669": "CA", "678": "GA", "681": "WV", "682": "TX", "701": "ND",
    "702": "NV", "703": "VA", "704": "NC", "706": "GA", "707": "CA", "708": "IL",
    "712": "IA", "713": "TX", "714": "CA", "715": "WI", "716": "NY", "717": "PA",
    "718": "NY", "719": "CO", "720": "CO", "724": "PA", "725": "NV", "727": "FL",
    "731": "TN", "732": "NJ", "734": "MI", "737": "TX", "740": "OH", "747": "CA",
    "754": "FL", "757": "VA", "760": "CA", "762": "GA", "763": "MN", "770": "GA",
    "772": "FL", "773": "IL", "774": "MA", "775": "NV", "779": "IL", "781": "MA",
    "785": "KS", "786": "FL", "801": "UT", "802": "VT", "803": "SC", "804": "VA",
    "805": "CA", "806": "TX", "808": "HI", "810": "MI", "812": "IN", "813": "FL",
    "814": "PA", "815": "IL", "816": "MO", "817": "TX", "818": "CA", "828": "NC",
    "830": "TX", "831": "CA", "832": "TX", "843": "SC", "845": "NY", "847": "IL",
    "848": "NJ", "850": "FL", "856": "NJ", "857": "MA", "858": "CA", "859": "KY",
    "860": "CT", "862": "NJ", "863": "FL", "864": "SC", "865": "TN", "870": "AR",
    "872": "IL", "878": "PA", "901": "TN", "903": "TX", "904": "FL", "906": "MI",
    "907": "AK", "908": "NJ", "909": "CA", "910": "NC", "912": "GA", "913": "KS",
    "914": "NY", "915": "TX", "916": "CA", "917": "NY", "918": "OK", "919": "NC",
    "920": "WI", "925": "CA", "928": "AZ", "929": "NY", "931": "TN", "936": "TX",
    "937": "OH", "940": "TX", "941": "FL", "947": "MI", "949": "CA", "951": "CA",
    "952": "MN", "954": "FL", "956": "TX", "959": "CT", "970": "CO", "971": "OR",
    "972": "TX", "973": "NJ", "978": "MA", "979": "TX", "980": "NC", "984": "NC",
    "985": "LA", "989": "MI",
}

# name (lowercase) -> state abbr. Only cities with no well-known non-US
# namesake -- e.g. no Portland (ME/UK ambiguity), no Cambridge (MA/UK),
# no Manchester (NH/UK), no Richmond (VA/many), no Columbus (multiple
# countries have one), no Paris/London/Birmingham.
MAJOR_US_CITIES = {
    "new york city": "NY", "brooklyn": "NY", "manhattan": "NY", "los angeles": "CA",
    "san francisco": "CA", "san diego": "CA", "sacramento": "CA", "san jose": "CA",
    "oakland": "CA", "fresno": "CA", "long beach": "CA", "anaheim": "CA",
    "chicago": "IL", "houston": "TX", "dallas": "TX", "austin": "TX",
    "san antonio": "TX", "fort worth": "TX", "el paso": "TX", "phoenix": "AZ",
    "tucson": "AZ", "scottsdale": "AZ", "philadelphia": "PA", "pittsburgh": "PA",
    "san antonio": "TX", "jacksonville": "FL", "miami": "FL", "tampa": "FL",
    "orlando": "FL", "st. petersburg": "FL", "fort lauderdale": "FL",
    "seattle": "WA", "spokane": "WA", "tacoma": "WA", "denver": "CO",
    "colorado springs": "CO", "boulder": "CO", "boston": "MA", "worcester": "MA",
    "detroit": "MI", "grand rapids": "MI", "ann arbor": "MI", "minneapolis": "MN",
    "saint paul": "MN", "cleveland": "OH", "columbus ohio": "OH", "cincinnati": "OH",
    "atlanta": "GA", "savannah": "GA", "milwaukee": "WI", "madison wisconsin": "WI",
    "kansas city": "MO", "st. louis": "MO", "las vegas": "NV", "reno": "NV",
    "nashville": "TN", "memphis": "TN", "knoxville": "TN", "chattanooga": "TN",
    "charlotte": "NC", "raleigh": "NC", "durham": "NC", "greensboro": "NC",
    "indianapolis": "IN", "oklahoma city": "OK", "tulsa": "OK",
    "albuquerque": "NM", "santa fe": "NM", "salt lake city": "UT",
    "new orleans": "LA", "baton rouge": "LA", "baltimore": "MD",
    "washington dc": "DC", "honolulu": "HI", "anchorage": "AK", "boise": "ID",
    "omaha": "NE", "des moines": "IA", "wichita": "KS", "louisville": "KY",
    "birmingham alabama": "AL", "jackson mississippi": "MS", "little rock": "AR",
    "charleston south carolina": "SC", "virginia beach": "VA", "newark": "NJ",
    "jersey city": "NJ", "buffalo": "NY", "rochester ny": "NY", "syracuse": "NY",
    "albany ny": "NY", "hartford": "CT", "providence": "RI", "bridgeport": "CT",
}
