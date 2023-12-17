# -*- coding: utf-8 -*-
{
    'name': "Facturación Electrónica - Perú",
    'summary':
        """
        Generación de documentos electrónicos para envío a SUNAT.
        Facturas, boletas, notas de crédito y notas de débito. Comunicación de baja y Resumen de boletas.
        Formato UBL - 2.1
        """,
    'description': """
        Este módulo permite facturar electrónicamente.
    """,
    'author': " ",
    'website': " ",
    'category': 'Uncategorized',
    'version': '0.1',
    'depends': ['base', 'sale', 'account', 'odoope_einvoice_base', 'odoope_ruc_validation', 'odoope_toponyms', 'backend_theme_v10', 'web_responsive'],
    'data': [
        'views/views.xml',
        'data/account_journal.xml',
        'data/sequences.xml'
    ],
    'external_dependencies':{
        "python":['cryptography','ipaddress',"signxml","cffi","pytesseract","bs4","suds"]
    }
}