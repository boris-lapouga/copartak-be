import requests
import re
import json
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from utils.get_car_details import get_car_details
import math
from urllib.parse import urlencode, unquote
from fuzzywuzzy import fuzz
from fuzzywuzzy import process

CLEARVIN_URL = "https://www.clearvin.com/en/copart-vin-check/?lotNumber="
EPICVIN_URL = "https://epicvin.com/check-vin-number-and-get-the-vehicle-history-report/checkout/"
CARS_URL = "https://www.cars.com/shopping/results"

app = Flask(__name__)
CORS(app)

@app.route('/api/price-estimation', methods=['OPTIONS'])
def price_estimation_options():
    return jsonify(success=True), 200

@app.route('/api/price-estimation', methods=['POST'])
def price_estimation():
    if not request.data:
        abort(400, description="No data provided in the request")

    try:
        data = request.get_json()
        print('DATA', data)
    except Exception as e:
        abort(400, description="Invalid JSON provided")

    if not data:
        return jsonify({"error": "No data provided or failed to parse JSON"}), 400

    required_keys = ["vin", "lotId", "year", "make", "model", "mileage"]

    if not all(key in data for key in required_keys):
        abort(400, description="Required keys are missing from the request data")

    # Get the lotId and make a GET request to clearvin
    lotId = data.get('lotId')
    clearvin_response = requests.get(CLEARVIN_URL + lotId)
    soup = BeautifulSoup(clearvin_response.text, 'html.parser')

    # Extract the data from the clearvin response
    vehicle_card = soup.find('div', id='vehicle-card')
    title = vehicle_card.find('h3')
    details = vehicle_card.find_all('strong', class_='details-card__stat-value')
    
    if title and title.text and "***" not in title.text:
        clearvin_car_details = get_car_details(title.text)

    if details and len(details) >= 4:
        clearvin_data = {
            "trim": clearvin_car_details['trim'] or details[0].text,
            "engine": details[1].text,
            "style": details[2].text,
            "msrp": details[3].text
        }

    # Get the VIN and make a GET request to epicvin
    vin = data.get('vin')
    epicvin_response = requests.get(EPICVIN_URL + vin)
    soup = BeautifulSoup(epicvin_response.text, 'html.parser')

    # Extract the model or trim from the epicvin response
    precheck = soup.find('div', id='precheck')
    model_trim = re.sub(r'^\D*', '', precheck.h1.text)
    model_trim = re.sub(r'\s*#.*$', '', model_trim)
    model_trim = model_trim.strip()

    parsed_car_details = get_car_details(model_trim)

    print('CLEARVIN', clearvin_data)
    print('EPICVIN', parsed_car_details)

    trim = ''

    if data.get('trim'):
        trim = data.get('trim')
    if 'trim' in clearvin_data:
        trim += " " + clearvin_data['trim']
    if 'trim' in parsed_car_details:
        trim += " " + parsed_car_details['trim']

    if not data.get('trim') and clearvin_data['trim']:
        data['trim'] = clearvin_data['trim']

    if not data.get('trim') and parsed_car_details['trim']:
        data['trim'] = parsed_car_details['trim']

    trim = sort_by_length(trim)
    
    print('TRIM', trim)

    possible_slugs = generate_possible_slugs(data)
    print('SLUGS', possible_slugs)

    res_slugs_match = match_model('%s %s' % (data.get('model'), data.get('trim')), possible_slugs)
    print('SLUGS_MATCH', res_slugs_match)

    with open('./mapping/carscom_models.json') as f:
        cars_models = json.load(f)

    # Filter the models by the make name
    models = [model['slug'] for model in cars_models['models'] if model['make_name'].lower() == parsed_car_details["make"]]

    print('ALL_CHOICES', models)
    res_match_model = match_model('%s %s' % (data.get('model'), trim), models + possible_slugs, 3)
    print('MATCH_MODELS', data.get('model'), res_match_model)

    res_match_trim = match_model('%s %s %s' % (' '.join(possible_slugs), data.get('model'), trim), res_match_model)

    print('TRIMS', trim, res_match_trim)

    mileage = int(data.get('mileage'))
    rounded_mileage = math.ceil(mileage / 10000) * 10000

    # Prepare the query string for the cars.com request
    query_string = {
        'stock_type': 'all',
        'makes[]': [data.get('make')],
        'models[]': 
            possible_slugs[:3] + [t[0] for t in res_match_model[:3]]
        ,
        'list_price_max': '',
        'maximum_distance': 'all',
        'zip': 92620,
        'year_min': data.get('year'),
        'year_max': data.get('year'),
        'deal_ratings': [],
        'dealer_id': '',
        'keyword': '',
        'list_price_min': '',
        'mileage_max': int(rounded_mileage),
        'monthly_payment': '',
        'page_size': 20,
        'sort': 'listed_at_desc',
        'stock_type': 'used'
    }

    if data.get('cylinder_counts'):
        query_string['cylinder_counts[]'] = data.get('cylinder_counts')

    if data.get('transmission'):
        query_string['transmission_slugs[]'] = [data.get('transmission')]

    if data.get('drivetrain'):
        query_string['drivetrain_slugs[]'] = [data.get('drivetrain')]

    url_query_string = urlencode(query_string, doseq=True)
    decoded_query_string = unquote(url_query_string)

    full_url = CARS_URL + "?" + decoded_query_string
    print(full_url)

    # Make a GET request to cars.com
    cars_response = requests.get(CARS_URL, params=query_string)
    soup = BeautifulSoup(cars_response.text, 'html.parser')

    # Parse the response and collect the data
    vehicles = soup.find_all('div', class_='vehicle-card')
    vehicle_data = []
    for vehicle in vehicles:
        vehicle_title = vehicle.find('h2', class_='title').text
        vehicle_price = vehicle.find('span', class_='primary-price').text
        vehicle_data.append({
            'title': vehicle_title,
            'price': vehicle_price,
        })

    total_data = {
        "msrp": clearvin_data['msrp'],
        "carscom": vehicle_data
    }
    # Return the data as a JSON response
    return jsonify(total_data)

def match_model(query, choices, limit=None):
    if not limit:
        return process.extractOne(query, choices)
    
    return process.extractBests(query, choices, limit=limit)

def sort_by_length(input_string):
    words = input_string.split()
    words.sort(key=len, reverse=True)
    return ' '.join(words)

def generate_possible_slugs(data):
    make = data.get('make', '').replace(' ', '_').lower()
    model = data.get('model', '').replace(' ', '_').lower()
    trim = data.get('trim', '').replace(' ', '_').lower()

    if '-' in model:
        model = model.replace('-', '_')

    # Generate all combinations of make, model and trim
    combinations = []
    if make and model and trim:
        combinations = [
            f"{make}-{model}_{trim}",
            f"{make}-{model}",
            f"{make}-{trim}",
        ]
    elif make and model:
        combinations = [f"{make}-{model}"]
    elif make and trim:
        combinations = [f"{make}-{trim}"]
    elif make:
        combinations = [make]
    elif model and trim:
        combinations = [f"{model}_{trim}", model]
    elif model:
        combinations = [model]
    elif trim:
        combinations = [trim]

    # Remove duplicates
    combinations = list(set(combinations))

    return combinations

if __name__ == '__main__':
    app.run(debug=True, port=3050)
