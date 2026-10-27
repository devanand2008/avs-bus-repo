import csv
import io
from pathlib import Path
from decimal import Decimal
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from fleet.calculations import D,q,FORMULAS

def safe_cell(v):
    s='' if v is None else str(v)
    return "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s

def rows_for(payload,kind):
    headers=['Bus number','Registration','Period start (IST)','Period end exclusive (IST)','GPS km','Delivered L','Expected L','Disappearance L','Eligible residual L','Refills','Status','Fuel-based km shortage','Diesel shortage L (review)','Route km shortage','Boundary uncertainty L','Shortage quality']
    rows=[]
    for b in payload['buses']:
        rows.append([b['bus_number'],b['registration'],payload['period']['start'],payload['period']['end'],b['gps_km'],b['delivered_l'],b['expected_l'],b['disappearance_l'],b['residual_l'],b['refill_count'],b['status'],b.get('km_shortage_km'),b.get('diesel_shortage_l'),b.get('route_shortage_km'),b.get('uncertainty_l'),b.get('shortage_status','Not captured in this snapshot')])
    return headers,rows

def csv_report(payload,kind):
    output=io.StringIO(newline=''); w=csv.writer(output)
    w.writerow(['College Fleet Command',kind,payload['college']['name']])
    if payload.get('demo'): w.writerow(['SYNTHETIC DEMONSTRATION DATA — not college records'])
    headers,rows=rows_for(payload,kind); w.writerow(headers)
    for row in rows:w.writerow([safe_cell(v) for v in row])
    w.writerow([]);w.writerow(['DAILY GPS — calendar totals, separate from per-fill reconciliation'])
    w.writerow(['Bus number','Date','GPS km','Approved plan km','Deviation km (actual-plan)','Expected L','Manual fallback km','Quality','Revision','Mileage version IDs','Source GPS IDs'])
    for b in payload['buses']:
        for d in b['daily']:w.writerow([safe_cell(x) for x in [b['bus_number'],d['service_date'],d['gps_km'],d['planned_km'],d['deviation_km'],d['expected_l'],d['manual_km'],d['status'],d['revision'],';'.join(d['mileage_ids']),';'.join(d['gps_source_ids'])]])
    w.writerow([]);w.writerow(['PER FILLING — not calendar totals']);w.writerow(['Bus number','Occurrence','Litres','Standard range km','Actual interval km','Shortfall km','Equivalent L','Interval status'])
    for b in payload['buses']:
        for f in b.get('fill_intervals',[]):w.writerow([safe_cell(x) for x in [b['bus_number'],f['occurred_at'],f['litres'],f['standard_range_km'],f['actual_interval_km'],f['shortfall_km'],f['equivalent_l'],f['quality']]])
    w.writerow([]);w.writerow(['CASE DECISIONS — amounts counted once per approved case ID'])
    w.writerow(['Bus number','Case ID','State','Rule version','Decision','Approved amount INR','Financial approver'])
    for c in payload.get('cases',[]):w.writerow([safe_cell(c.get(k)) for k in ('bus_number','id','state','rule_version','decision','approved_amount','financial_approved_by')])
    w.writerow(['Snapshot SHA256',payload.get('snapshot_hash','')]);w.writerow(['Calculation version',payload['calculation_version']])
    return ('\ufeff'+output.getvalue()).encode('utf-8')

def pdf_report(payload,kind,signoffs=None):
    output=io.BytesIO(); styles=getSampleStyleSheet(); story=[]
    navy=colors.HexColor('#142b3c'); teal=colors.HexColor('#0e847d')
    def p(text,style='Normal'):return Paragraph(escape(str(text)),styles[style])
    def table(headers,rows,widths=None):
        t=Table([[p(h) for h in headers]]+[[p('Unknown' if x is None else x) for x in r] for r in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e0eeeb')),('TEXTCOLOR',(0,0),(-1,-1),navy),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#d6dfdf')),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]));return t
    logo=Path(__file__).resolve().parent/'assets'/'logo.png'
    story.append(Image(str(logo),width=78,height=78,hAlign='LEFT'))
    story.append(Spacer(1,8))
    story.extend([p('COLLEGE FLEET COMMAND','Title'),p(payload['college']['name'],'Heading2'),p(kind.replace('_',' ').title(),'Heading1'),p(f"{payload['period']['start']} to {payload['period']['end']} (exclusive) · Asia/Kolkata"),p(f"Calculation {payload['calculation_version']} · Frozen snapshot · {payload.get('close_status','provisional')}"),Spacer(1,12)])
    if payload.get('demo'):story.extend([p('SYNTHETIC DEMONSTRATION DATA — not college records','Heading2'),Spacer(1,8)])
    h,rows=rows_for(payload,kind)
    story.append(table(['Bus','GPS km','Delivered L','Expected L','Stock disappearance L','Eligible residual L','Refills'],[[r[0],r[4],r[5],r[6],r[7],r[8],r[9]] for r in rows],[55,85,90,90,110,110,65]))
    story.append(Spacer(1,12));story.append(p('Delivered fuel, estimated engine use and stock-adjusted disappearance are separate quantities. Unknown stock is never zero. A residual requires review; it is not an allegation.'))
    for b in payload['buses']:
        story.append(PageBreak());story.append(p(f"Bus {b['bus_number']} · {b['registration']}",'Heading1'))
        story.append(p(f"Survey readings: {', '.join(b['survey_readings']) or 'Unavailable'} km; mean {b['survey_mean_km'] or 'Unknown'}; scope {b['survey_scope'] or 'Unknown'}."))
        story.append(p(f"Mileage versions: {', '.join(m['id']+' ('+m['kmpl']+' km/L)' for m in b['mileage_versions']) or 'No approved standard'}. GPS coverage: {b['coverage_pct'] or 'Unknown'}%."));story.append(Spacer(1,10))
        if 'shortage_status' in b and kind!='monthly':
            story.append(table(['Shortage review measure','Value'],[
                ['Stock-adjusted fuel range (km)',b.get('reconciled_range_km')],
                ['Fuel-based km shortage (km)',b.get('km_shortage_km')],
                ['Diesel shortage / review variance (L)',b.get('diesel_shortage_l')],
                ['Route km shortage: approved plan minus GPS (km)',b.get('route_shortage_km')],
                ['Boundary uncertainty (+/- L)',b.get('uncertainty_l')],
                ['Quality',b.get('shortage_status')]], [400,205]))
            story.append(p('Positive review variances are not confirmed losses or authorised deductions. Fuel-based kilometre and litre figures are different units of the same variance; do not add or charge them twice. Unknown inputs remain unknown.'));story.append(Spacer(1,10))
        if kind=='gps_weekly':
            hdr=['Service date','GPS km','Approved plan km','Deviation km','Expected L','Quality / revision']
            rr=[[d['service_date'],d['gps_km'],d['planned_km'],d['deviation_km'],d['expected_l'],f"{d['status']} / {d['revision']}"] for d in b['daily']]
            story.append(table(hdr,rr,[100,90,100,90,90,135]));story.append(Spacer(1,8))
            denominator=sum(d['gps_km'] is not None for d in b['daily'])
            average=q(D(b['gps_km'])/denominator) if denominator and b['gps_km'] is not None else None
            story.append(p(f"Average denominator: {denominator} days with validated distance; average: {average} km/day. Calendar weekly totals exclude missing days from the average denominator."))
            story.append(p('Reason / remarks: ____________________________________________________________________'))
        elif kind=='fuel_weekly':
            story.append(p('Per-filling reconciliation (interval after each delivery until the next posted delivery). Kept separate from calendar weekly totals.','Heading3'))
            story.append(table(['Fill occurrence','Delivered L','Standard range km','Actual interval km','Shortfall km','Equivalent L','Quality'],[[f[k] for k in ('occurred_at','litres','standard_range_km','actual_interval_km','shortfall_km','equivalent_l','quality')] for f in b.get('fill_intervals',[])],[160,65,85,85,75,65,70]))
            story.append(p('Authority decision / remarks: __________________________________________________________'))
        else:
            legacy=q(D(b['delivered_l'])*D(b['standard_kmpl'])) if b['standard_kmpl'] else None
            story.append(table(['Monthly measure','Value'],[['Legacy delivered × fixed mileage (km)',legacy],['Actual validated GPS distance (km)',b['gps_km']],['Legacy minus actual (km)',q(legacy-D(b['gps_km'])) if legacy is not None and b['gps_km'] is not None else None],['Opening measured stock (L)',b['opening_l']],['Closing measured stock (L)',b['closing_l']],['Approved transfers in / out (L)',f"{b['transfers_in_l']} / {b['transfers_out_l']}"],['Stock-adjusted disappearance (L)',b['disappearance_l']],['Eligible review residual (L)',b['residual_l']],['Boundary measurement uncertainty (L)',b['uncertainty_l']]]+([['Stock-adjusted fuel range (km)',b.get('reconciled_range_km')],['Fuel-based km shortage (km)',b.get('km_shortage_km')],['Diesel shortage / review variance (L)',b.get('diesel_shortage_l')],['Route km shortage (km)',b.get('route_shortage_km')],['Shortage quality',b.get('shortage_status')]] if 'shortage_status' in b else []),[400,205]))
            story.append(p('Legacy distance is unavailable when multiple mileage versions apply. Stock reconciliation is shown independently. Shortages are review variances, not confirmed losses or authorised deductions. Km and litres are different units of the same fuel variance; do not count them twice.'))
    story.append(PageBreak());story.append(p('Review cases and authorised decisions','Heading1'))
    cases=payload.get('cases',[])
    story.append(table(['Bus','Case / rule','State','Decision','Approved INR'],[[c['bus_number'],c['id'][:8]+' / '+c['rule'],c['state'],c['decision'],c['approved_amount'] if c['financial_approved_by'] else None] for c in cases],[50,170,115,180,90]))
    amount=sum((D(c['approved_amount']) for c in cases if c['approved_amount'] is not None and c['financial_approved_by']),Decimal(0))
    story.append(p(f'Unique approved case amounts: INR {amount}. No automatic salary deduction.'))
    mapping=payload['college'].get('report_fields',{})
    story.append(p(f"Configurable legacy fields: Chairman = {mapping.get('chairman','UNCONFIRMED')}; Corres = {mapping.get('corres','UNCONFIRMED')}; deduction slots = {mapping.get('deduction_slots','UNCONFIRMED')}. Cases are not limited to five."))
    story.append(Spacer(1,18));story.append(table(['Prepared','Independently verified','Approved / signed'],[[signoffs.get('prepared','________________') if signoffs else '________________',signoffs.get('verified','________________') if signoffs else '________________',signoffs.get('approved','________________') if signoffs else '________________']],[200,200,205]))
    story.append(Spacer(1,14));story.append(p('Calculation notes','Heading2'))
    for key,(formula,unit) in FORMULAS.items():story.append(p(f'{key} [{unit}]: {formula}'))
    story.append(p('Midnight portions use elapsed-time allocation of accepted geodesic segments. This is a reporting allocation estimate, not a measured road-distance trace between missing fixes.'))
    story.append(p(f"Snapshot hash: {payload.get('snapshot_hash','')}"))
    def footer(canvas,doc):
        canvas.drawImage(str(logo),32,10,width=24,height=24,preserveAspectRatio=True,mask='auto')
        canvas.setFillColor(teal);canvas.setFont('Helvetica',8);canvas.drawString(64,22,'College Fleet Command | Private operational report');canvas.drawRightString(810,22,f'Page {doc.page}')
    doc=SimpleDocTemplate(output,pagesize=landscape(A4),rightMargin=32,leftMargin=32,topMargin=30,bottomMargin=38,title=f'College Fleet Command - {kind}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
