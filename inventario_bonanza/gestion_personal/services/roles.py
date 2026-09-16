"""Asignación declarativa entre roles y sus paneles."""


DASHBOARD_BY_ROLE = {
    'global_admin': 'dashboard_global_admin',
    'medico': 'dashboard_medico',
    'rh': 'dashboard_rrhh',
    'operador': 'dashboard_operador',
    'admin_mina': 'dashboard_admin',
    'admin_molino': 'dashboard_admin',
    'seguridad_fisica': 'dashboard_seguridad',
    'tecnico_seguridad': 'dashboard_tecnico',
}


def dashboard_for_role(user_type):
    return DASHBOARD_BY_ROLE.get(user_type)
