"""Búsqueda de colaboradores para paneles y flujos operativos."""

from django.db.models import Q

from .scoping import people_for_user


def resolve_person_search(user, query):
    """Devuelve una coincidencia única o una lista corta para que el usuario elija."""
    normalized_query = (query or '').strip()
    if not normalized_query:
        return None, people_for_user(user).none()

    filters = (
        Q(id_number__icontains=normalized_query)
        | Q(first_name__icontains=normalized_query)
        | Q(last_name__icontains=normalized_query)
    )
    first_term = normalized_query.split()[0]
    if first_term != normalized_query:
        filters |= Q(first_name__icontains=first_term)
    matches = people_for_user(user).filter(filters).order_by('last_name', 'first_name')
    exact_match = matches.filter(id_number__iexact=normalized_query).first()
    if exact_match:
        return exact_match, matches.none()

    candidates = list(matches[:2])
    if len(candidates) == 1:
        return candidates[0], matches.none()
    return None, matches[:15]
