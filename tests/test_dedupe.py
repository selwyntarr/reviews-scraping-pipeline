from pipeline.stages.dedupe import Rec, score_pair


def rec(name, hn="", street="", lat=None, lon=None, phone="", source="osm"):
    from pipeline.normalize import norm_housenumber, norm_name, norm_phone, norm_street

    return Rec(
        raw_id=hash(name) & 0xFFFF,
        source=source,
        source_id=name,
        name=name,
        name_norm=norm_name(name),
        housenumber=norm_housenumber(hn),
        street=street,
        street_norm=norm_street(street),
        zip="",
        lat=lat,
        lon=lon,
        phone=norm_phone(phone),
        website=None,
        cuisine=None,
        category=None,
        last_inspection=None,
    )


def test_exact_same_venue_scores_one():
    a = rec("FRENCH ROAST", "2340", "BROADWAY", 40.7855, -73.9765, source="dohmh")
    b = rec("French Roast", "2340", "Broadway", 40.7856, -73.9766)
    assert score_pair(a, b)["score"] >= 0.95


def test_subset_name_is_not_a_perfect_match():
    a = rec("NAN XIANG XIAO LONG BAO", "15", "SAINT MARKS PLACE", 40.7295, -73.9885, source="dohmh")
    b = rec("The Bao", "13", "Saint Marks Place", 40.7296, -73.9886)
    assert score_pair(a, b)["name_sim"] < 0.75


def test_slash_separated_concepts_match_either_part():
    a = rec(
        "FELLINI CUCINA / FELLINI COFFEE",
        "176",
        "7 AVENUE SOUTH",
        40.7345,
        -74.0025,
        source="dohmh",
    )
    b = rec("Fellini Coffee", "174", "7th Avenue South", 40.7346, -74.0026)
    assert score_pair(a, b)["name_sim"] == 1.0


def test_different_business_same_address_scores_below_match():
    a = rec("POPEYES LOUISIANA KITCHEN", "934", "8 AVENUE", 40.7625, -73.9885, source="dohmh")
    b = rec("Deep Indian Kitchen", "934", "8th Avenue", 40.7626, -73.9886)
    assert score_pair(a, b)["name_sim"] < 0.75


def test_far_apart_different_street_is_penalised():
    a = rec("Joe's Pizza", "7", "CARMINE STREET", 40.7305, -74.0025, source="dohmh")
    b = rec("Joe's Pizza", "1435", "Broadway", 40.7550, -73.9870)
    assert score_pair(a, b)["score"] < 0.70
