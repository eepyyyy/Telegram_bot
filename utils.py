import unicodedata
import re


def convert_text(s: str) -> str:
    """
        Takes any Language string and converts to alphanumeric characters in Unicode
    Args:
        s: String input
    Returns:
        alphanumeric characters in Unicode
    """
    # 1. Decompose characters (e.g., 'é' becomes 'e' + '´')
    nfkd_form = unicodedata.normalize('NFKD', s)

    # 2. Strip out accents/diacritics and force lowercase
    only_ascii = nfkd_form.encode('ASCII', 'ignore').decode('utf-8').lower()

    # 3. Keep only core alphanumeric characters across any language script
    #    \w matches alphanumeric characters in Unicode
    return "".join(re.findall(r'\w+', only_ascii))

