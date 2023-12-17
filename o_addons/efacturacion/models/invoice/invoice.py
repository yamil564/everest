#!/usr/bin/env python
# -*- coding: utf-8 -*-
from odoo import fields,models,api,_
from utils.InvoiceLine import Factura
from utils.Boleta import Boleta
from utils.NotaCredito import NotaCredito
from utils.NotaDebito import NotaDebito
import xml.etree.ElementTree as ET
from signxml import XMLSigner, XMLVerifier,methods
import requests
import zipfile
import base64
import os
from suds.client import Client
from suds.wsse import *
import requests
import logging

from odoo.exceptions import UserError, RedirectWarning, ValidationError
"""
class product(models.Model):
    _inherit = "product.product"
    qty_location=fields.One2many("stock.quant","product_id",string="Stock por Ubicacion")

class productTemplate(models.Model):
    _inherit = "product.template"
    qty_location=fields.One2many("stock.quant","product_id",string="Stock por Ubicacion")
"""


class productuon(models.Model):
    _inherit = "product.uom"
    code=fields.Char(string="Codigo")
    description=fields.Char(string="Descripcion")

class invoiceline(models.Model):
    _inherit = "account.invoice.line"

    def _tipo_afectacion_igv(self):
        return self.env["einvoice.catalog.07"].search([["code","=",10]])

    tipo_afectacion_igv = fields.Many2one("einvoice.catalog.07",default=_tipo_afectacion_igv)
    no_onerosa = fields.Boolean(related="tipo_afectacion_igv.no_onerosa",string="No Oneroso")

    tipo_sistema_calculo_isc = fields.Many2one("einvoice.catalog.08")

    @api.one
    @api.depends('tipo_afectacion_igv')
    def _change_tipo_afectacion_igv(self):
        if self.tipo_afectacion_igv.no_onerosa:
            self.invoice_line_tax_ids.unlink()
        else:
            taxes_id=[tax_id.id for tax_id in self.product_id.taxes_id]
            self.invoice_line_tax_ids=[(6,0,taxes_id)]
        self._compute_price()

    invoice_line_tax_ids = fields.Many2many('account.tax',
                                            'account_invoice_line_tax', 'invoice_line_id', 'tax_id',
                                            string='Taxes',
                                            domain=[('type_tax_use', '!=', 'none'), '|', ('active', '=', False),
                                                    ('active', '=', True)], oldname='invoice_line_tax_id',
                                            compute='_change_tipo_afectacion_igv')

    @api.one
    @api.depends('price_unit', 'discount', 'invoice_line_tax_ids', 'quantity',
                 'product_id', 'invoice_id.partner_id', 'invoice_id.currency_id', 'invoice_id.company_id',
                 'invoice_id.date_invoice')
    def _compute_price(self):
        currency = self.invoice_id and self.invoice_id.currency_id or None
        price = self.price_unit * (1 - (self.discount or 0.0) / 100.0)
        taxes = False
        if self.invoice_line_tax_ids:
            taxes = self.invoice_line_tax_ids.compute_all(price, currency, self.quantity, product=self.product_id,
                                                          partner=self.invoice_id.partner_id)
        self.price_subtotal = price_subtotal_signed = taxes['total_excluded'] if taxes else self.quantity * price
        if self.invoice_id.currency_id and self.invoice_id.company_id and self.invoice_id.currency_id != self.invoice_id.company_id.currency_id:
            price_subtotal_signed = self.invoice_id.currency_id.with_context(date=self.invoice_id.date_invoice).compute(
                price_subtotal_signed, self.invoice_id.company_id.currency_id)
        sign = self.invoice_id.type in ['in_refund', 'out_refund'] and -1 or 1
        self.price_subtotal_signed = price_subtotal_signed * sign


class rescompany(models.Model):
    _inherit = "res.company"
    private=fields.Text("Clave Privada")
    public=fields.Text("Clave Publica")
    sunat_username=fields.Char("Usuario SOL")
    sunat_password=fields.Char("Password SOL")

class accountjournal(models.Model):
    _inherit = "account.journal"
    codigo_documento = fields.Char("Codigo de tipo de Documento")


    def _list_invoice_type(self):
        catalogs=self.env["einvoice.catalog.01"].search([])
        list=[]
        for cat in catalogs:
            list.append((cat.code,cat.name))
        return list

    invoice_type_code_id=fields.Selection(string="Tipo de Documento",selection=_list_invoice_type)

class accounttax(models.Model):
    _inherit = "account.tax.group"
    code = fields.Char("Codigo",required=True)
    description = fields.Char("Descripcion",required=True)
    name_code = fields.Char("Nombre del Codigo",required=True)


class invoice(models.Model):
    _inherit = "account.invoice"

    documentoXML=fields.Text("Documento XML",default=" ")
    documentoXMLcliente=fields.Binary("Documento para el cliente")
    documentoXMLcliente_fname = fields.Char("Prueba name", compute="set_xml_filename")
    documentoZip=fields.Binary("Documento Zip",default="")
    documentoEnvio=fields.Text("Documento de Envio")
    paraEnvio=fields.Text("XML para cliente")
    documentoRespuesta=fields.Text("Documento de Respuesta XML")
    documentoRespuestaZip=fields.Binary("Documento de Respuesta ZIP")
    documentoEnvioTicket = fields.Text("Documento de Envio Ticket")

    mensajeSUNAT = fields.Text("Mensaje de respuesta")
    codigoretorno = fields.Char("Código retorno")

    operacionTipo = fields.Selection(string="Tipo de operación", selection=[('01', 'Venta interna'), ('02', 'Exportación'), ('04', 'Anticipo')], default='01')
    #####
    # invoice_number_begin=fields.Boolean('Flag button', compute='_compute_number_begin')
    #####

    def set_xml_filename(self):
        self.documentoXMLcliente_fname = str(self.number) + ".xml"
    
    def _compute_zip(self):
        self.documentoRespuestaZip = ET.fromstring(str(self.documentoRespuesta))[1][0][0].text

    def _compute_number_begin(self):
        # etroot = ET.fromstring(str(self.documentoRespuesta))[1][0][0]
        # print ET.fromstring(str(self.documentoRespuesta))[1][0][0].text
        # print self.number
        
        if self.number:
            if 'F' in self.number:
                # self.invoice_number_begin=True
                return True
            else:
                # self.invoice_number_begin=False
                return False
        

    def enviar_correo(self):
        template = self.env.ref('account.email_template_edi_invoice', False)
        """
        mail_compose=self.env["mail.compose.message"].sudo().create({
            "model":'account.invoice',
            "res_id":self.id,
            "use_template":bool(template),
            "template_id":template and template.id or False,
            "composition_mode":'comment',
            "mark_invoice_as_sent":True,
            "custom_layout":"account.mail_template_data_notification_email_account_invoice"
        })
        """
        mail_id = self.env["mail.template"].sudo().browse(template.id).send_mail(self.id)
        mail = self.env["mail.mail"].sudo().browse(mail_id)
        mail.send()

    
    def _list_reference_code_credito(self):
        catalogs=self.env["einvoice.catalog.09"].search([])
        list=[]
        for cat in catalogs:
            list.append((cat.code,cat.name))
        return list

    response_code=fields.Char("response_code")

    response_code_credito = fields.Selection(string="Código de motivo",
                                     selection=_list_reference_code_credito)

    def _list_reference_code_debito(self):
        catalogs=self.env["einvoice.catalog.10"].search([])
        list=[]
        for cat in catalogs:
            list.append((cat.code,cat.name))
        return list

    response_code_debito = fields.Selection(string="Código de motivo",
                                     selection=_list_reference_code_debito)
    referenceID = fields.Char("Referencia")
    motivo = fields.Text("Motivo")

    """
    @api.one
    @api.depends('journal_id')
    def _get_invoice_type_code(self):
        return self.journal_id.invoice_type_code_id
    """

    @api.model
    def default_get(self, fields_list):
        res = super(invoice, self).default_get(fields_list)

        journal_id=self.env['account.journal'].search([['invoice_type_code_id', '=', self._context.get("type_code")]], limit=1)
        res["journal_id"] = journal_id.id

        return res

        """
        if self._context.get('default_journal_id', False):
            return self.env['account.journal'].browse(self._context.get('default_journal_id'))
        inv_type = self._context.get('type', 'out_invoice')
        inv_types = inv_type if isinstance(inv_type, list) else [inv_type]
        company_id = self._context.get('company_id', self.env.user.company_id.id)
        domain = [
            ('type', 'in', filter(None, map(TYPE2JOURNAL.get, inv_types))),
            ('company_id', '=', company_id),
        ]
        return self.env['account.journal'].search(domain, limit=1)
        """

    invoice_type_code = fields.Selection(string="Tipo de Comprobante",
                                         store=True,
                                         related="journal_id.invoice_type_code_id")

    @api.one
    @api.depends('invoice_line_ids.price_subtotal','invoice_line_ids.tipo_afectacion_igv', 'tax_line_ids.amount', 'currency_id', 'company_id', 'date_invoice','type')
    def _compute_total_venta(self):
        self.total_venta_gravado=sum(
            [line.price_subtotal for line in self.invoice_line_ids if line.tipo_afectacion_igv.type=="gravado"])
        self.total_venta_inafecto = sum(
            [line.price_subtotal for line in self.invoice_line_ids if line.tipo_afectacion_igv.type=="inafecto"])
        self.total_venta_exonerada = sum(
            [line.price_subtotal for line in self.invoice_line_ids if line.tipo_afectacion_igv.type=="exonerado"])
        self.total_venta_gratuito = sum(
            [line.product_id.lst_price*line.quantity for line in self.invoice_line_ids if line.price_unit == 0])
        # self.total_venta_gratuito=sum(
        #     [line.price_subtotal for line in self.invoice_line_ids if line.tipo_afectacion_igv.type=="gravado" and line.tipo_afectacion_igv.no_onerosa==True])
        self.total_descuentos = sum(
            [line.quantity*line.price_unit*line.discount/100 for line in self.invoice_line_ids])
        
        # if self.total_venta_gratuito > 0.0:
        #     self.amount_total = self.amount_total - self.total_venta_gratuito

    total_venta_gravado=fields.Monetary("Gravado",default=0.0,compute="_compute_total_venta")
    total_venta_inafecto=fields.Monetary("Inafecto",default=0.0,compute="_compute_total_venta")
    total_venta_exonerada=fields.Monetary("Exonerado",default=0.0,compute="_compute_total_venta")
    total_venta_gratuito=fields.Monetary("Gratuita",default=0.0,compute="_compute_total_venta")
    total_descuentos=fields.Monetary("Total Descuentos",default=0.0,compute="_compute_total_venta")
    
    digestvalue=fields.Char("DigestValue")

    @api.multi
    def firmar(self):
        data_unsigned=ET.fromstring(self.documentoXML.encode('utf-8').strip())
        namespaces = {
            "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "ccts": "urn:un:unece:uncefact:documentation:2",
            "ds": "http://www.w3.org/2000/09/xmldsig#",
            "qdt": "urn:oasis:names:specification:ubl:schema:xsd:QualifiedDatatypes-2",
            "sac": "urn:sunat:names:specification:ubl:peru:schema:xsd:SunatAggregateComponents-1",
            "udt": "urn:un:unece:uncefact:data:specification:UnqualifiedDataTypesSchemaModule:2",
            "xsi": "http://www.w3.org/  2001/XMLSchema-instance",
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
        }

        if self.invoice_type_code=="01" or self.invoice_type_code=="03":
            namespaces.update({"":"urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"})
        elif self.invoice_type_code=="07":
            namespaces.update({"":"urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"})
        elif self.invoice_type_code=="08":
            namespaces.update({"":"urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2"})

        for prefix, uri in namespaces.iteritems():
            ET.register_namespace(prefix, uri)
        uri="/var/lib/odoo/"
        print self.company_id.partner_id.vat
        print str(self.journal_id.invoice_type_code_id)
        print str(self.number)
        name_file=self.company_id.partner_id.vat+"-"+str(self.journal_id.invoice_type_code_id)+"-"+str(self.number)
        file=open(uri+name_file+".xml","w")
        signed_root = XMLSigner(
                                    method=methods.enveloped,
                                    digest_algorithm='sha1',
                                    c14n_algorithm='http://www.w3.org/TR/2001/REC-xml-c14n-20010315'
                                ).sign(data_unsigned,
                                       key=str(self.company_id.private),
                                       cert=str(self.company_id.public),
                                       )
        signed_root[0][1][0][0].set("Id","SignatureMT")
        self.digestvalue=signed_root[0][1][0][0][0][2][2].text
        file.write(ET.tostring(signed_root))
        file.close()
        
        xfile=open(uri+name_file+".xml","r")
        xml_file = xfile.read()
        self.documentoXMLcliente=base64.b64encode(str(xml_file))
        xfile.close()
		
        zf=zipfile.ZipFile(uri+name_file+".zip",mode="w")
        try:
            zf.write(uri+name_file+".xml",arcname=name_file+".xml")
        except Exception, e:
            zf.close()
        zf.close()

        f = open(uri+name_file+".zip", 'rb')
        data_file = f.read()
        self.documentoZip=base64.b64encode(str(data_file))
        self.documentoXML=ET.tostring(signed_root)
        f.close()

        FacturaObject=  Factura()
        EnvioXML=FacturaObject.sendBill(username=self.company_id.partner_id.vat + self.company_id.sunat_username,
                               password=self.company_id.sunat_password,
                               namefile=name_file+".zip",
                               contentfile=self.documentoZip)
        self.documentoEnvio=EnvioXML.toprettyxml("        ")


    @api.multi
    def enviar(self):
        # Beta
        # url="https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService"
        # Homologacion
        # url="https://www.sunat.gob.pe:443/ol-ti-itcpgem-sqa/billService"
        
        # Produccion
        url="https://e-factura.sunat.gob.pe/ol-ti-itcpfegem/billService"
        # https://www.sunat.gob.pe/ol-ti-itcpgem-sqa/billService

        r=requests.post(url=url,
                        data=self.documentoEnvio,
                        headers={"Content-Type":"text/xml"})
        # os.system("echo 'RESPUESTA:"+r.text+"'")
        try:
            self.documentoRespuestaZip=ET.fromstring(r.text)[1][0][0].text
        except Exception, e:
            self.documentoRespuestaZip=""
        self.documentoRespuesta=r.text

    @api.multi
    def descargarRespuesta(self):
        name_file = "R-"+self.company_id.partner_id.vat + "-" + str(self.journal_id.invoice_type_code_id) + "-" + str(self.number)
        url = self.env["ir.config_parameter"].search([["key", "=", "web.base.url"]])["value"]
        file_url = url + "/web/content/account.invoice/" + str(self.id) + "/documentoRespuestaZip/" +name_file + ".zip"
        return {
            "type": "ir.actions.act_url",
            "url": file_url,
            "target": "new"
        }
####################
######################
    @api.multi
    def estadoTicket(self):
        FacturaObject = Factura()
        EnvioXML = FacturaObject.getStatus(
            username = str(self.company_id.sunat_username),
            password = str(self.company_id.sunat_password),
            ruc = str(self.company_id.partner_id.vat),
            tipo = str(self.invoice_type_code),
            numero = self.number
            )
        self.documentoEnvioTicket=EnvioXML.toprettyxml("        ")
        self.enviarTicket()
    
    @api.multi
    def enviarTicket(self):
        # Beta
        # url="https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService"
        # Homologacion
        # url="https://www.sunat.gob.pe:443/ol-ti-itcpgem-sqa/billService"
        
        # Produccion
        # URL 1
        url="https://e-factura.sunat.gob.pe/ol-ti-itcpfegem/billService"
        # url = "https://www.sunat.gob.pe/ol-it-wsconscpegem/billConsultService"
        r=requests.post(url=url,
                        data=self.documentoEnvioTicket,
                        headers={"Content-Type":"text/xml"})
        
        # codigo = ET.fromstring(r.text)[0][0][0][0].text
        # mensaje = ET.fromstring(r.text)[0][0][0][1].text
        print ET.fromstring(r.text.encode('utf-8'))[0][0][0][1].text.encode('utf-8')
        # mensaje = ET.fromstring(r.text.encode('utf-8'))[0][0][0][1].text.encode('utf-8')
        #ET.fromstring(r.text)[0][0][0][1].text
        codigo = ET.fromstring(r.text.encode('utf-8'))[0][0][0][0].text.encode('utf-8')
        if codigo == '0001':
            self.codigoretorno = "Aceptado"
        elif (codigo == '0002') or (codigo == '0003'):
            self.codigoretorno = "Rechazado/Baja"
        else:
            self.codigoretorno = "Error"
        self.mensajeSUNAT = ET.fromstring(r.text.encode('utf-8'))[0][0][0][1].text.encode('utf-8')
        
        self.documentoRespuesta=r.text
#####################
####################
    @api.multi
    def action_invoice_open(self):
        # lots of duplicate calls to action_invoice_open, so we remove those already open
        to_open_invoices = self.filtered(lambda inv: inv.state != 'open')
        if to_open_invoices.filtered(lambda inv: inv.state not in ['proforma2', 'draft']):
            raise UserError(_("Invoice must be in draft or Pro-forma state in order to validate it."))
        to_open_invoices.action_date_assign()
        to_open_invoices.action_move_create()
        
        if self.invoice_type_code in ('01','03'):
            self.generarFactura()
        # elif self.invoice_type_code == '03':
        #     self.generarBoletaVenta()
        elif self.invoice_type_code == '07':
            self.generarNotaCredito()
        elif self.invoice_type_code == '08':
            self.generarNotaDebito()
        
        self.firmar()
        response = to_open_invoices.invoice_validate()
        # self.enviar_correo()
        return response
####################
#####################
######################