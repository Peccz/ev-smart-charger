from datetime import date

def get_swedish_holidays(year):
    """
    Returns a set of Swedish public holidays (dates) for a given year.
    Includes fixed dates and a few calculated moveable ones.
    """
    holidays = {
        date(year, 1, 1),   # Nyårsdagen
        date(year, 1, 6),   # Trettondedag jul
        date(year, 5, 1),   # Första maj
        date(year, 6, 6),   # Nationaldagen
        date(year, 12, 24), # Julafton (de facto)
        date(year, 12, 25), # Juldagen
        date(year, 12, 26), # Annandag jul
        date(year, 12, 31), # Nyårsafton (de facto)
    }

    # Moveable holidays (hardcoded for 2025-2027 to avoid complex Easter logic)
    moveable = {
        2025: {
            date(2025, 4, 18), # Långfredag
            date(2025, 4, 21), # Annandag påsk
            date(2025, 5, 29), # Kristihimmelsfärd
            date(2025, 6, 20), # Midsommarafton
            date(2025, 6, 21), # Midsommardagen
        },
        2026: {
            date(2026, 4, 3),  # Långfredag
            date(2026, 4, 6),  # Annandag påsk
            date(2026, 5, 14), # Kristihimmelsfärd
            date(2026, 6, 19), # Midsommarafton
            date(2026, 6, 20), # Midsommardagen
        },
        2027: {
            date(2027, 3, 26), # Långfredag
            date(2027, 3, 29), # Annandag påsk
            date(2027, 5, 6),  # Kristihimmelsfärd
            date(2027, 6, 25), # Midsommarafton
            date(2027, 6, 26), # Midsommardagen
        }
    }
    
    if year in moveable:
        holidays.update(moveable[year])
        
    return holidays

def is_swedish_holiday(dt):
    """Checks if a datetime or date object is a Swedish holiday."""
    if hasattr(dt, 'date'):
        d = dt.date()
    else:
        d = dt
    return d in get_swedish_holidays(d.year)
