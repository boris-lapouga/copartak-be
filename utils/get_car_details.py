def get_car_details(raw_title_words):
    title_words = raw_title_words.strip().split(' ')

    year = title_words.pop(0).strip()
    make = title_words.pop(0).strip().lower()

    trim = title_words.pop().strip().lower()
    model = ' '.join(title_words).strip().lower()

    if not model or len(model) <= 0:
        model = trim
        trim = ''

    return {
        "year": year, 
        "make": make, 
        "model": model, 
        "trim": trim
    }
