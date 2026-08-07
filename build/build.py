"""Build IFA_Contacts_Dashboard.xlsx from contacts.json + the original source workbook."""
import json, datetime
from collections import Counter, OrderedDict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, NamedStyle
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.formatting.rule import CellIsRule, DataBarRule, ColorScaleRule
from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList

ROWS = 600                 # capacity of the RawData table (data lives in rows 2..600)
LAST = ROWS                # last data row
CONTACT_ROWS = 600         # rows rendered on the Contacts tab

rows = json.load(open('contacts.json'))

# ------------------------------------------------------------------ palette
NAVY   = '1F3864'
BLUE   = '2E5C8A'
LBLUE  = 'DCE6F1'
BAND   = 'F4F7FB'
GREY   = 'EDEDED'
GREYTX = '808080'
GREEN  = 'D8EFDC'
GREENT = '18682F'
AMBER  = 'FFF0CC'
RED    = 'FBE0E0'
REDT   = 'A61C1C'
WHITE  = 'FFFFFF'
INPUT  = '0000FF'          # blue text = type here

F   = 'Arial'
def font(sz=10, b=False, color='000000', it=False):
    return Font(name=F, size=sz, bold=b, color=color, italic=it)

thin  = Side(style='thin', color='BFBFBF')
BOX   = Border(left=thin, right=thin, top=thin, bottom=thin)
UNDER = Border(bottom=Side(style='medium', color=NAVY))

def fill(hexcode):
    return PatternFill('solid', fgColor=hexcode)

def set_widths(ws, widths):
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w

def value_labels():
    d = DataLabelList()
    d.showVal, d.showCatName, d.showSerName = True, False, False
    d.showLegendKey, d.showPercent, d.showBubbleSize = False, False, False
    return d

wb = openpyxl.Workbook()
wb.remove(wb.active)

# =============================================================== SETUP SHEET
st = wb.create_sheet('Setup')
st.sheet_properties.tabColor = NAVY
st.sheet_view.showGridLines = False

EVENTS = [
    ('H2O AM IFA Symposium (October 2025)', 'Oct-25 Symposium', datetime.date(2025, 10, 1)),
    ('2nd Edition H2O AM IFA Symposium (May 2026)', 'May-26 Symposium', datetime.date(2026, 5, 1)),
    ('Macro Lunch series', 'Macro Lunch', datetime.date(2026, 7, 23)),
]

st['B2'] = 'IFA CONTACT DATABASE  —  SETUP & USER GUIDE'
st['B2'].font = font(16, True, NAVY)
st['B3'] = 'Everything in this workbook is driven by the RawData tab. Add a contact there and every other tab updates itself.'
st['B3'].font = font(10, False, GREYTX, it=True)

guide = [
    ('1.', 'ADD A CONTACT', "Go to the RawData tab, scroll to the first empty row and type into the WHITE columns (Name .. Notes). "
                            "The GREY columns to the right calculate themselves — never type in them."),
    ('2.', 'DROPDOWNS', "Firm, Contact Type, Source, Met?, Invested?, Email Sent, LinkedIn and every event column are dropdowns. "
                        "To add a new choice, add it to the lists on the right of this tab."),
    ('3.', 'ADD AN EVENT', "Type the event name / short name / date into the EVENTS table below (rows 4 and 5 are free). "
                           "A new column instantly appears in RawData and a new line appears on the Dashboard."),
    ('4.', 'READ THE NUMBERS', "Dashboard = who they are and where they come from.  Meeting Stats = how the meeting effort is going.  "
                               "Contacts = the searchable directory (use the filter boxes at the top)."),
    ('5.', 'CAPACITY', f"The workbook is set up for {ROWS - 1} contacts. To go beyond that, select rows and use "
                       "Formulas > Name Manager to extend the c_* ranges, or run the ExtendCapacity macro."),
    ('6.', 'MACROS (optional)', "Everything above works with formulas only — no macros required. IFA_Contacts_Macros.bas adds "
                                "one-click sorting, an add-contact form and a duplicate checker if you want them."),
]
r = 5
for num, head, body in guide:
    st.cell(r, 2, num).font = font(10, True, BLUE)
    st.cell(r, 3, head).font = font(10, True, NAVY)
    c = st.cell(r, 4, body)
    c.font = font(10)
    c.alignment = Alignment(wrap_text=True, vertical='top')
    st.merge_cells(start_row=r, start_column=4, end_row=r, end_column=11)
    st.row_dimensions[r].height = 28
    r += 1

# ---- events table
st['B13'] = 'EVENTS'
st['B13'].font = font(12, True, NAVY)
st['C13'] = '(blue cells are yours to edit — adding a row here adds an event everywhere)'
st['C13'].font = font(9, False, GREYTX, it=True)
for i, h in enumerate(['#', 'Event name (full)', 'Short name (used on charts)', 'Date'], start=2):
    c = st.cell(14, i, h)
    c.font = font(10, True, WHITE)
    c.fill = fill(BLUE)
    c.border = BOX
    c.alignment = Alignment(horizontal='center')
EV_ROW0 = 15                       # events occupy rows 15..19
for i in range(5):
    rr = EV_ROW0 + i
    st.cell(rr, 2, f'Event {i + 1}').font = font(10, True)
    for col in (3, 4, 5):
        cell = st.cell(rr, col)
        cell.font = font(10, color=INPUT)
        cell.border = BOX
        cell.fill = fill(WHITE)
    if i < len(EVENTS):
        st.cell(rr, 3, EVENTS[i][0])
        st.cell(rr, 4, EVENTS[i][1])
        st.cell(rr, 5, EVENTS[i][2]).number_format = 'dd-mmm-yy'
    st.cell(rr, 2).border = BOX

# ---- colour legend
LEGEND = [
    (WHITE, '000000', 'White cell', 'Type here — this is your data (RawData columns B to S).'),
    (GREY, '000000', 'Grey cell', 'Calculated. Typing over it breaks the formula for that row.'),
    ('FFF2CC', INPUT, 'Yellow cell', 'A filter or a switch — change it to change what you see.'),
    (GREEN, GREENT, 'Green', 'Good news: met, attended, invested.'),
    (RED, REDT, 'Red', 'Needs attention: declined, or over 120 days since the last meeting.'),
]
st.cell(21, 2, 'COLOUR LEGEND').font = font(12, True, NAVY)
for i, (bg, fg, lab, meaning) in enumerate(LEGEND):
    rr = 22 + i
    c = st.cell(rr, 2, lab)
    c.fill, c.font, c.border = fill(bg), font(10, True, fg), BOX
    c.alignment = Alignment(horizontal='center')
    m = st.cell(rr, 3, meaning)
    m.font = font(9, color='595959')
    st.merge_cells(start_row=rr, start_column=3, end_row=rr, end_column=11)

# ---- assumptions / mapping
st['B29'] = 'HOW THE ORIGINAL FILE WAS TRANSLATED  (assumptions — change any cell in RawData if one is wrong)'
st['B29'].font = font(12, True, NAVY)
notes = [
    "Source workbook: IFA_Meeting_List.xlsx — tabs Meeting List, Attendance, Branch Directors, Mass Email PIAS, ILP Data. "
    "All five are kept unchanged at the end of this workbook.",
    "Contacts were merged on name (case and spacing ignored). Two people with the same name at DIFFERENT firms were kept separate.",
    "Oct-25 Symposium, from 'Meeting List' column D: Yes = Attended, Not Available = Declined, No = No Reply, blank = Not Invited.",
    "May-26 Symposium: the 'Attendance' tab is that event's attendance sheet — 66 registered, 55 ticked = Attended, the other 11 = No Show. "
    "Column K 'Accepted' supplies Declined / No Reply for everyone else; column J blank = Not Invited.",
    "'Macro Lunch' and 'Overseas' written in the Invited column were moved out: Macro Lunch became its own event, Overseas became a Declined + a note.",
    "Met? = Yes wherever the source held a last-meeting date, even where its 'Meeting (Thomas)' column still said No "
    "(9 rows). # Meetings: the source only records ONE date per contact, so everyone met was given 1 meeting — "
    "overtype column I in RawData with the true count whenever you know it.",
    "AUM comes from the 'ILP Data' tab (53 contacts, S$922m in total — matches that tab's own control figure).",
    "Branch Directors: the Firm column was filled down; branch names, LinkedIn URLs and 'already in CRM' flags were folded into Notes.",
]
r = 30
for n in notes:
    c = st.cell(r, 2, '•  ' + n)
    c.font = font(9, color='595959')
    c.alignment = Alignment(wrap_text=True, vertical='top')
    st.merge_cells(start_row=r, start_column=2, end_row=r, end_column=11)
    st.row_dimensions[r].height = 24
    r += 1

# ---- validation lists (kept to the right, out of the way)
firm_counts = Counter(x['firm'] for x in rows)
FIRMS = [f for f, _ in sorted(firm_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
TYPES = ['Adviser', 'Branch Director', 'Consultant', 'Product / Platform', 'Other']
SOURCES = ['Meeting List', 'Branch Directors', 'Mass Email PIAS', 'ILP Data', 'Event', 'Referral', 'LinkedIn', 'Other']
MET = ['Yes', 'No', 'TBC']
STATUS = ['Attended', 'No Show', 'Accepted', 'Invited', 'No Reply', 'Declined', 'Not Invited']
YN = ['Yes', 'No', 'TBC']
LI = ['Yes', 'No', 'No LinkedIn found']
ENGAGE = ['Event attendee', 'Met (no event)', 'Invited only', 'Contacted only', 'Not yet contacted']

LIST_COL = OrderedDict([
    ('Firms', (13, FIRMS, 60)),                # column M
    ('Contact Type', (15, TYPES, 10)),         # O
    ('Source', (17, SOURCES, 14)),             # Q
    ('Met?', (19, MET, 8)),                    # S
    ('Event status', (21, STATUS, 12)),        # U
    ('Yes / No', (23, YN, 8)),                 # W
    ('LinkedIn', (25, LI, 8)),                 # Y
    ('Engagement', (27, ENGAGE, 8)),           # AA
])
for title, (col, vals, cap) in LIST_COL.items():
    c = st.cell(13, col, title)
    c.font = font(10, True, WHITE)
    c.fill = fill(BLUE)
    c.border = BOX
    for i in range(cap):
        cell = st.cell(14 + i, col, vals[i] if i < len(vals) else None)
        cell.font = font(10)
        cell.border = BOX
    st.column_dimensions[get_column_letter(col)].width = 24

# filter lists = "(All)" + the list, for the Contacts tab dropdowns
FILTERS = OrderedDict([
    ('Firm filter', (30, ['(All)'] + FIRMS, 62)),
    ('Met filter', (32, ['(All)'] + MET, 8)),
    ('Event filter', (34, ['(All)'] + [e[1] for e in EVENTS], 8)),
    ('Engagement filter', (36, ['(All)'] + ENGAGE, 8)),
])
for title, (col, vals, cap) in FILTERS.items():
    c = st.cell(13, col, title)
    c.font = font(10, True, WHITE)
    c.fill = fill(GREYTX)
    c.border = BOX
    for i in range(cap):
        cell = st.cell(14 + i, col, vals[i] if i < len(vals) else None)
        cell.font = font(10)
        cell.border = BOX
    st.column_dimensions[get_column_letter(col)].width = 24
# the event filter list must follow the Setup events table, not a frozen copy
for i in range(3):
    st.cell(15 + i, 34, f'=IF(Setup!$D${EV_ROW0 + i}="","",Setup!$D${EV_ROW0 + i})')
for i in range(3, 5):
    st.cell(15 + i, 34, f'=IF(Setup!$D${EV_ROW0 + i}="","",Setup!$D${EV_ROW0 + i})').font = font(10)

set_widths(st, {1: 2, 2: 14, 3: 34, 4: 24, 5: 12})
for col in 'FGHIJKL':
    st.column_dimensions[col].width = 13

# ============================================================= RAWDATA SHEET
rd = wb.create_sheet('RawData')
rd.sheet_properties.tabColor = '7F7F7F'

INPUT_HEADERS = [
    ('ID', 6), ('Name', 26), ('Email', 30), ('Firm', 20), ('Contact Type', 15),
    ('Source', 22), ('Met?', 8), ('Last Meeting', 13), ('# Meetings', 10),
    ('Invested?', 10), ('AUM (S$)', 14), ('Email Sent', 11), ('LinkedIn Contacted', 16),
]
EVENT_COLS = [14, 15, 16, 17, 18]          # N..R
AUTO_HEADERS = [
    ('Notes', 40),
    ('# Events Invited', 11), ('# Events Attended', 11), ('Events Attended', 22),
    ('Days Since Meeting', 12), ('Engagement', 16),
]
# column map
C_ID, C_NAME, C_EMAIL, C_FIRM, C_TYPE, C_SRC, C_MET, C_DATE, C_MTG, C_INV, C_AUM, C_MAIL, C_LI = range(1, 14)
C_E1, C_E5 = 14, 18
C_NOTES = 19
C_EINV, C_EATT, C_ENAMES, C_DAYS, C_ENGAGE = 20, 21, 22, 23, 24
C_SORT, C_PASS, C_SEQ, C_FUP = 25, 26, 27, 28

for col, (h, w) in enumerate(INPUT_HEADERS, start=1):
    rd.cell(1, col, h)
    rd.column_dimensions[get_column_letter(col)].width = w
for i, col in enumerate(EVENT_COLS):
    rd.cell(1, col, f'=IF(Setup!$C${EV_ROW0 + i}="","Event {i + 1} (free — name it in Setup)",Setup!$C${EV_ROW0 + i})')
    rd.column_dimensions[get_column_letter(col)].width = 20
for i, (h, w) in enumerate(AUTO_HEADERS):
    col = C_NOTES + i
    rd.cell(1, col, h)
    rd.column_dimensions[get_column_letter(col)].width = w
for col, h in [(C_SORT, '_sort'), (C_PASS, '_pass'), (C_SEQ, '_seq'), (C_FUP, '_followup')]:
    rd.cell(1, col, h)
    rd.column_dimensions[get_column_letter(col)].width = 9
    rd.column_dimensions[get_column_letter(col)].hidden = True

for col in range(1, C_FUP + 1):
    c = rd.cell(1, col)
    c.font = font(10, True, WHITE)
    c.fill = fill(NAVY if col <= C_NOTES else GREYTX)
    c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    c.border = BOX
rd.row_dimensions[1].height = 32
rd.freeze_panes = 'C2'

# ---- write the data
for i, rec in enumerate(rows):
    r = i + 2
    rd.cell(r, C_NAME, rec['name'])
    rd.cell(r, C_EMAIL, rec['email'])
    rd.cell(r, C_FIRM, rec['firm'])
    rd.cell(r, C_TYPE, rec['ctype'])
    rd.cell(r, C_SRC, rec['source'])
    rd.cell(r, C_MET, rec['met'])
    if rec['lastmtg']:
        d = rd.cell(r, C_DATE, datetime.date.fromisoformat(rec['lastmtg']))
        d.number_format = 'dd-mmm-yy'
    rd.cell(r, C_MTG, rec['mtgs'])
    rd.cell(r, C_INV, rec['invested'])
    if rec['aum'] != '':
        rd.cell(r, C_AUM, rec['aum']).number_format = '#,##0'
    rd.cell(r, C_MAIL, rec['mailsent'])
    rd.cell(r, C_LI, rec['linkedin'])
    for j, f_ in enumerate(['e1', 'e2', 'e3', 'e4', 'e5']):
        rd.cell(r, C_E1 + j, rec[f_] if j < len(EVENTS) else 'Not Invited')
    rd.cell(r, C_NOTES, rec['notes'])

SC = lambda i: f'Setup!$D${EV_ROW0 + i}'   # event short-name cell

for r in range(2, LAST + 1):
    rd.cell(r, C_ID, f'=IF($B{r}="","",COUNTA($B$2:$B{r}))')
    rd.cell(r, C_EINV,
            f'=IF($B{r}="","",COUNTA($N{r}:$R{r})-COUNTIF($N{r}:$R{r},"Not Invited"))')
    rd.cell(r, C_EATT, f'=IF($B{r}="","",COUNTIF($N{r}:$R{r},"Attended"))')
    rd.cell(r, C_ENAMES,
            f'=IF($B{r}="","",_xlfn.TEXTJOIN(", ",TRUE,'
            + ','.join(f'IF(${get_column_letter(C_E1 + i)}{r}="Attended",{SC(i)},"")' for i in range(5))
            + '))')
    rd.cell(r, C_DAYS, f'=IF(OR($B{r}="",NOT(ISNUMBER($H{r}))),"",TODAY()-$H{r})')
    rd.cell(r, C_ENGAGE,
            f'=IF($B{r}="","",IF($U{r}>0,"Event attendee",IF($G{r}="Yes","Met (no event)",'
            f'IF($T{r}>0,"Invited only",IF(OR($L{r}="Yes",$M{r}="Yes"),"Contacted only","Not yet contacted")))))')
    rd.cell(r, C_SORT,
            f'=IF($B{r}="","",COUNTIF(c_Firm,"<"&$D{r})+COUNTIFS(c_Firm,$D{r},c_Name,"<"&$B{r})'
            f'+COUNTIFS($D$2:$D{r},$D{r},$B$2:$B{r},$B{r}))')
    rd.cell(r, C_PASS,
            f'=IF($B{r}="","",IF(AND('
            f'OR(Contacts!$C$3="(All)",$D{r}=Contacts!$C$3),'
            f'OR(Contacts!$E$3="(All)",$G{r}=Contacts!$E$3),'
            f'OR(Contacts!$G$3="(All)",ISNUMBER(SEARCH(Contacts!$G$3,$V{r}))),'
            f'OR(Contacts!$I$3="(All)",$X{r}=Contacts!$I$3),'
            f'OR(Contacts!$K$3="",ISNUMBER(SEARCH(Contacts!$K$3,$B{r}&" "&$C{r}&" "&$D{r}&" "&$S{r})))'
            f'),1,0))')
    rd.cell(r, C_SEQ, f'=IF($Z{r}=1,COUNTIFS(c_Pass,1,c_Sort,"<="&$Y{r}),"")')
    rd.cell(r, C_FUP,
            f'=IF(OR($G{r}<>"Yes",NOT(ISNUMBER($H{r}))),"",'
            f'COUNTIFS(c_Met,"Yes",c_Date,"<"&$H{r})+COUNTIFS($G$2:$G{r},"Yes",$H$2:$H{r},$H{r}))')

    for col in range(1, C_FUP + 1):
        c = rd.cell(r, col)
        c.font = font(10)
        c.border = BOX
        if col >= C_EINV or col == C_ID:
            c.fill = fill(GREY)
        c.alignment = Alignment(horizontal='center' if col in
                                (C_ID, C_MET, C_DATE, C_MTG, C_INV, C_MAIL, C_LI, C_EINV, C_EATT, C_DAYS)
                                else 'left', vertical='center')
    rd.cell(r, C_DATE).number_format = 'dd-mmm-yy'
    rd.cell(r, C_AUM).number_format = '#,##0'
    rd.cell(r, C_MTG).number_format = '0'
    rd.cell(r, C_NOTES).alignment = Alignment(vertical='center')

rd.auto_filter.ref = f'A1:{get_column_letter(C_ENGAGE)}{LAST}'

# ---- dropdowns
def dv(formula, cols, allow_blank=True):
    d = DataValidation(type='list', formula1=formula, allow_blank=allow_blank, showErrorMessage=False)
    rd.add_data_validation(d)
    for col in cols:
        d.add(f'{get_column_letter(col)}2:{get_column_letter(col)}{LAST}')

dv('=lst_Firms', [C_FIRM])
dv('=lst_Type', [C_TYPE])
dv('=lst_Source', [C_SRC])
dv('=lst_Met', [C_MET, C_INV])
dv('=lst_YN', [C_MAIL])
dv('=lst_LinkedIn', [C_LI])
dv('=lst_Status', EVENT_COLS)

# ---- conditional formatting
rng_met = f'{get_column_letter(C_MET)}2:{get_column_letter(C_MET)}{LAST}'
rd.conditional_formatting.add(rng_met, CellIsRule(operator='equal', formula=['"Yes"'],
                                                  fill=fill(GREEN), font=font(10, True, GREENT)))
ev_rng = f'{get_column_letter(C_E1)}2:{get_column_letter(C_E5)}{LAST}'
for val, bg, fg in [('"Attended"', GREEN, GREENT), ('"No Show"', AMBER, '9C6500'),
                    ('"Declined"', RED, REDT), ('"Not Invited"', 'F7F7F7', 'A6A6A6')]:
    rd.conditional_formatting.add(ev_rng, CellIsRule(operator='equal', formula=[val],
                                                     fill=fill(bg), font=font(10, color=fg)))
rng_days = f'{get_column_letter(C_DAYS)}2:{get_column_letter(C_DAYS)}{LAST}'
rd.conditional_formatting.add(rng_days, CellIsRule(operator='greaterThan', formula=['120'],
                                                   fill=fill(RED), font=font(10, True, REDT)))

# ---------------------------------------------------------------- names
def name(n, ref):
    wb.defined_names.add(DefinedName(n, attr_text=ref))

for nm, col in [('c_Name', C_NAME), ('c_Email', C_EMAIL), ('c_Firm', C_FIRM), ('c_Type', C_TYPE),
                ('c_Source', C_SRC), ('c_Met', C_MET), ('c_Date', C_DATE), ('c_Mtgs', C_MTG),
                ('c_Invested', C_INV), ('c_AUM', C_AUM), ('c_Mail', C_MAIL), ('c_LinkedIn', C_LI),
                ('c_Notes', C_NOTES), ('c_EvtInv', C_EINV), ('c_EvtAtt', C_EATT),
                ('c_EvtNames', C_ENAMES), ('c_Days', C_DAYS), ('c_Engage', C_ENGAGE),
                ('c_Sort', C_SORT), ('c_Pass', C_PASS), ('c_Seq', C_SEQ), ('c_FUp', C_FUP)]:
    L = get_column_letter(col)
    name(nm, f'RawData!${L}$2:${L}${LAST}')
for i in range(5):
    name(f'c_E{i + 1}', f'RawData!${get_column_letter(C_E1 + i)}$2:${get_column_letter(C_E1 + i)}${LAST}')

for nm, (col, _v, cap) in LIST_COL.items():
    key = {'Firms': 'lst_Firms', 'Contact Type': 'lst_Type', 'Source': 'lst_Source', 'Met?': 'lst_Met',
           'Event status': 'lst_Status', 'Yes / No': 'lst_YN', 'LinkedIn': 'lst_LinkedIn',
           'Engagement': 'lst_Engage'}[nm]
    L = get_column_letter(col)
    name(key, f'Setup!${L}$14:${L}${13 + cap}')
for nm, (col, _v, cap) in FILTERS.items():
    key = {'Firm filter': 'f_Firm', 'Met filter': 'f_Met', 'Event filter': 'f_Event',
           'Engagement filter': 'f_Engage'}[nm]
    L = get_column_letter(col)
    name(key, f'Setup!${L}$14:${L}${13 + cap}')

# ============================================================ SHARED HELPERS
def sheet_title(ws, title, subtitle, last_col=13):
    ws.sheet_view.showGridLines = False
    ws.merge_cells(start_row=1, start_column=2, end_row=1, end_column=last_col)
    c = ws.cell(1, 2, title)
    c.font = font(18, True, NAVY)
    ws.row_dimensions[1].height = 26
    ws.merge_cells(start_row=2, start_column=2, end_row=2, end_column=last_col)
    c = ws.cell(2, 2, subtitle)
    c.font = font(9.5, False, GREYTX, it=True)
    ws.cell(3, 2, None)

def section(ws, row, text, last_col=13, note=''):
    c = ws.cell(row, 2, text)
    c.font = font(12, True, NAVY)
    for col in range(2, last_col + 1):
        ws.cell(row, col).border = UNDER
    if note:
        n = ws.cell(row, 6, note)
        n.font = font(9, False, GREYTX, it=True)

def kpi(ws, row, col, label, formula, numfmt='#,##0'):
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 2)
    ws.merge_cells(start_row=row + 1, start_column=col, end_row=row + 1, end_column=col + 2)
    l = ws.cell(row, col, label.upper())
    l.font = font(8.5, True, BLUE)
    l.alignment = Alignment(horizontal='center', vertical='center')
    l.fill = fill(LBLUE)
    v = ws.cell(row + 1, col, formula)
    v.font = font(18, True, NAVY)
    v.alignment = Alignment(horizontal='center', vertical='center')
    v.fill = fill(BAND)
    v.number_format = numfmt
    for cc in range(col, col + 3):
        ws.cell(row, cc).border = BOX
        ws.cell(row + 1, cc).border = BOX
    ws.row_dimensions[row].height = 15
    ws.row_dimensions[row + 1].height = 30

def table_header(ws, row, col0, headers, widths=None):
    # widths are applied per sheet at the end - tables stacked in the same
    # columns would otherwise each overwrite the previous one's width
    for i, h in enumerate(headers):
        c = ws.cell(row, col0 + i, h)
        c.font = font(9.5, True, WHITE)
        c.fill = fill(BLUE)
        c.border = BOX
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    ws.row_dimensions[row].height = 30

def body_cell(ws, row, col, value=None, numfmt=None, bold=False, align='right', banded=False):
    c = ws.cell(row, col, value)
    c.font = font(10, bold)
    c.border = BOX
    c.alignment = Alignment(horizontal=align, vertical='center')
    if numfmt:
        c.number_format = numfmt
    if banded:
        c.fill = fill(BAND)
    return c

KPI_COLS = [2, 5, 8, 11]

# ============================================================== DASHBOARD
db = wb.create_sheet('Dashboard')
db.sheet_properties.tabColor = '2E75B6'
sheet_title(db, 'IFA CONTACT DASHBOARD',
            'Live overview of every contact in the database. Add or edit a contact on the RawData tab and every number here moves with it.')
db.cell(3, 2, '=\"Contacts in database: \"&TEXT(COUNTA(c_Name),\"#,##0\")&\"    |    Refreshed: \"&TEXT(TODAY(),\"d mmm yyyy\")').font = font(9, True, GREYTX)

TILES = [
    (5,  'Total contacts',        '=COUNTA(c_Name)', '#,##0'),
    (5,  'Firms covered',         '=SUMPRODUCT((c_Firm<>"")/COUNTIF(c_Firm,c_Firm&""))', '#,##0'),
    (5,  'Contacts met',          '=COUNTIF(c_Met,"Yes")', '#,##0'),
    (5,  'Meeting coverage',      '=IFERROR(COUNTIF(c_Met,"Yes")/COUNTA(c_Name),0)', '0.0%'),
    (8,  'Total meetings',        '=SUM(c_Mtgs)', '#,##0'),
    (8,  'Invited to an event',   '=COUNTIF(c_EvtInv,">0")', '#,##0'),
    (8,  'Attended an event',     '=COUNTIF(c_EvtAtt,">0")', '#,##0'),
    (8,  'Event attendance rate', '=IFERROR(COUNTIF(c_EvtAtt,">0")/COUNTIF(c_EvtInv,">0"),0)', '0.0%'),
    (11, 'Met in last 90 days',   '=COUNTIFS(c_Date,">="&TODAY()-90)', '#,##0'),
    (11, 'Never contacted',       '=COUNTIF(c_Engage,"Not yet contacted")', '#,##0'),
    (11, 'Investors',             '=COUNTIF(c_Invested,"Yes")', '#,##0'),
    (11, 'ILP AUM tracked (S$m)', '=SUM(c_AUM)/1000000', '#,##0'),
]
for i, (row, label, formula, fmt) in enumerate(TILES):
    kpi(db, row, KPI_COLS[i % 4], label, formula, fmt)

# ---- by firm
FIRM_R0 = 15
section(db, 14, 'WHERE THEY COME FROM  —  CONTACTS BY FIRM',
        note='sorted by size; % Met = share of that firm you have already met')
FH = ['Firm', 'Contacts', '% of DB', 'Met', '% Met', 'Meetings',
      'Invited to events', 'Attended events', 'Investors', 'ILP AUM (S$m)']
table_header(db, FIRM_R0, 2, FH, [26, 10, 9, 8, 9, 10, 11, 11, 10, 12])
for i, f_ in enumerate(FIRMS):
    r = FIRM_R0 + 1 + i
    band = i % 2 == 1
    body_cell(db, r, 2, f_, align='left', banded=band)
    body_cell(db, r, 3, f'=COUNTIF(c_Firm,$B{r})', '#,##0', banded=band)
    body_cell(db, r, 4, f'=IFERROR($C{r}/COUNTA(c_Name),0)', '0.0%', banded=band)
    body_cell(db, r, 5, f'=COUNTIFS(c_Firm,$B{r},c_Met,"Yes")', '#,##0', banded=band)
    body_cell(db, r, 6, f'=IFERROR($E{r}/$C{r},0)', '0.0%', banded=band)
    body_cell(db, r, 7, f'=SUMIF(c_Firm,$B{r},c_Mtgs)', '#,##0', banded=band)
    body_cell(db, r, 8, f'=COUNTIFS(c_Firm,$B{r},c_EvtInv,">0")', '#,##0', banded=band)
    body_cell(db, r, 9, f'=COUNTIFS(c_Firm,$B{r},c_EvtAtt,">0")', '#,##0', banded=band)
    body_cell(db, r, 10, f'=COUNTIFS(c_Firm,$B{r},c_Invested,"Yes")', '#,##0', banded=band)
    body_cell(db, r, 11, f'=SUMIF(c_Firm,$B{r},c_AUM)/1000000', '#,##0.0', banded=band)
FIRM_RN = FIRM_R0 + len(FIRMS)
TOT_R = FIRM_RN + 1
body_cell(db, TOT_R, 2, 'TOTAL', align='left', bold=True).fill = fill(LBLUE)
for col, fmt in [(3, '#,##0'), (5, '#,##0'), (7, '#,##0'), (8, '#,##0'), (9, '#,##0'), (10, '#,##0'), (11, '#,##0.0')]:
    L = get_column_letter(col)
    c = body_cell(db, TOT_R, col, f'=SUM({L}{FIRM_R0 + 1}:{L}{FIRM_RN})', fmt, bold=True)
    c.fill = fill(LBLUE)
body_cell(db, TOT_R, 4, f'=IFERROR($C{TOT_R}/COUNTA(c_Name),0)', '0.0%', bold=True).fill = fill(LBLUE)
body_cell(db, TOT_R, 6, f'=IFERROR($E{TOT_R}/$C{TOT_R},0)', '0.0%', bold=True).fill = fill(LBLUE)

CHK_R = TOT_R + 1
c = db.cell(CHK_R, 2, 'Contacts whose firm is missing from the Setup list (should be 0):')
c.font = font(9, True, GREYTX)
db.merge_cells(start_row=CHK_R, start_column=2, end_row=CHK_R, end_column=5)
chk = body_cell(db, CHK_R, 6, f'=COUNTA(c_Name)-$C${TOT_R}', '#,##0', bold=True, align='center')
db.conditional_formatting.add(f'F{CHK_R}', CellIsRule(operator='greaterThan', formula=['0'],
                                                      fill=fill(RED), font=font(10, True, REDT)))
db.conditional_formatting.add(f'F{CHK_R}', CellIsRule(operator='equal', formula=['0'],
                                                      fill=fill(GREEN), font=font(10, True, GREENT)))

db.conditional_formatting.add(f'C{FIRM_R0 + 1}:C{FIRM_RN}',
                              DataBarRule(start_type='num', start_value=0, end_type='max', color=BLUE))
db.conditional_formatting.add(f'F{FIRM_R0 + 1}:F{FIRM_RN}',
                              ColorScaleRule(start_type='num', start_value=0, start_color='FFFFFF',
                                             end_type='num', end_value=1, end_color='8ED18E'))

# ---- events
EV_R0 = CHK_R + 2
section(db, EV_R0, 'WHICH EVENT THEY CAME TO', note='status per contact lives in RawData columns N–R')
EH = ['Event', 'Date', 'Invited', 'Attended', 'No show', 'Declined', 'No reply', 'Pending', 'Attendance rate']
table_header(db, EV_R0 + 1, 2, EH, [30, 11, 10, 10, 9, 10, 10, 9, 12])
for i in range(5):
    r = EV_R0 + 2 + i
    band = i % 2 == 1
    L = get_column_letter(C_E1 + i)
    rng = f'c_E{i + 1}'
    body_cell(db, r, 2, f'=IF(Setup!$C${EV_ROW0 + i}="","(free slot {i + 1})",Setup!$C${EV_ROW0 + i})',
              align='left', banded=band)
    body_cell(db, r, 3, f'=IF(Setup!$E${EV_ROW0 + i}="","",Setup!$E${EV_ROW0 + i})', 'dd-mmm-yy', align='center', banded=band)
    body_cell(db, r, 4, f'=COUNTA({rng})-COUNTIF({rng},"Not Invited")', '#,##0', banded=band)
    body_cell(db, r, 5, f'=COUNTIF({rng},"Attended")', '#,##0', banded=band)
    body_cell(db, r, 6, f'=COUNTIF({rng},"No Show")', '#,##0', banded=band)
    body_cell(db, r, 7, f'=COUNTIF({rng},"Declined")', '#,##0', banded=band)
    body_cell(db, r, 8, f'=COUNTIF({rng},"No Reply")', '#,##0', banded=band)
    body_cell(db, r, 9, f'=COUNTIF({rng},"Invited")+COUNTIF({rng},"Accepted")', '#,##0', banded=band)
    body_cell(db, r, 10, f'=IFERROR($E{r}/$D{r},"")', '0.0%', banded=band)

# ---- engagement + source
ENG_R0 = EV_R0 + 8
section(db, ENG_R0, 'HOW WARM THEY ARE', note='')
table_header(db, ENG_R0 + 1, 2, ['Stage', 'Contacts', '% of DB'], [26, 10, 9])
for i, e in enumerate(ENGAGE):
    r = ENG_R0 + 2 + i
    band = i % 2 == 1
    body_cell(db, r, 2, e, align='left', banded=band)
    body_cell(db, r, 3, f'=COUNTIF(c_Engage,$B{r})', '#,##0', banded=band)
    body_cell(db, r, 4, f'=IFERROR($C{r}/COUNTA(c_Name),0)', '0.0%', banded=band)

SRC_LABELS = [('Meeting List', 'Meeting List'), ('Branch Directors', 'Branch Directors'),
              ('Mass Email PIAS', 'Mass Email PIAS'), ('ILP Data', 'ILP Data')]
db.cell(ENG_R0, 6, 'WHICH LIST THEY CAME FROM').font = font(12, True, NAVY)
table_header(db, ENG_R0 + 1, 6, ['Source list', 'Contacts', '% of DB'], [22, 10, 9])
for i, (lab, pat) in enumerate(SRC_LABELS):
    r = ENG_R0 + 2 + i
    band = i % 2 == 1
    body_cell(db, r, 6, lab, align='left', banded=band)
    body_cell(db, r, 7, f'=COUNTIF(c_Source,"*"&$F{r}&"*")', '#,##0', banded=band)
    body_cell(db, r, 8, f'=IFERROR($G{r}/COUNTA(c_Name),0)', '0.0%', banded=band)
db.cell(ENG_R0 + 3 + len(SRC_LABELS), 6,
        'A contact can sit on more than one list, so these add up to more than the total.').font = \
    font(8.5, False, GREYTX, it=True)

set_widths(db, {1: 2, 2: 28, 3: 11, 4: 9, 5: 9, 6: 10, 7: 11, 8: 11, 9: 11, 10: 10,
                11: 13, 12: 11, 13: 11, 14: 3})

# ---- charts
TOPN = min(10, len(FIRMS))
ch = BarChart()
ch.type, ch.style = 'bar', 10
ch.title = 'Contacts by firm (top 10)'
ch.y_axis.title, ch.x_axis.title = None, None
ch.add_data(Reference(db, min_col=3, min_row=FIRM_R0, max_row=FIRM_R0 + TOPN), titles_from_data=True)
ch.set_categories(Reference(db, min_col=2, min_row=FIRM_R0 + 1, max_row=FIRM_R0 + TOPN))
ch.height, ch.width = 10, 14
ch.legend = None
db.add_chart(ch, 'O5')

ch2 = BarChart()
ch2.type, ch2.grouping, ch2.style = 'col', 'clustered', 10
ch2.title = 'Event funnel'
ch2.add_data(Reference(db, min_col=4, max_col=5, min_row=EV_R0 + 1, max_row=EV_R0 + 2 + len(EVENTS) - 1),
             titles_from_data=True)
ch2.set_categories(Reference(st, min_col=4, min_row=EV_ROW0, max_row=EV_ROW0 + len(EVENTS) - 1))
ch2.height, ch2.width = 8, 14
ch2.dLbls = value_labels()
db.add_chart(ch2, 'O27')

ch3 = DoughnutChart()
ch3.title = 'Engagement mix'
ch3.add_data(Reference(db, min_col=3, min_row=ENG_R0 + 1, max_row=ENG_R0 + 1 + len(ENGAGE)),
             titles_from_data=True)
ch3.set_categories(Reference(db, min_col=2, min_row=ENG_R0 + 2, max_row=ENG_R0 + 1 + len(ENGAGE)))
ch3.height, ch3.width = 8, 14
db.add_chart(ch3, 'O44')

# =========================================================== MEETING STATS
ms = wb.create_sheet('Meeting Stats')
ms.sheet_properties.tabColor = '548235'
sheet_title(ms, 'MEETING STATISTICS',
            'Built from the Met? / Last Meeting / # Meetings columns of RawData. '
            'The source file records one LAST MEETING date per contact, so the monthly split below shows each contact once, in the month you last saw them.')

MTILES = [
    (5, 'Total meetings',        '=SUM(c_Mtgs)', '#,##0'),
    (5, 'Contacts met',          '=COUNTIF(c_Met,"Yes")', '#,##0'),
    (5, 'Database met',          '=IFERROR(COUNTIF(c_Met,"Yes")/COUNTA(c_Name),0)', '0.0%'),
    (5, 'Meetings per contact',  '=IFERROR(SUM(c_Mtgs)/COUNTIF(c_Met,"Yes"),0)', '0.00'),
    (8, 'First meeting',         '=IFERROR(MIN(c_Date),"")', 'dd-mmm-yy'),
    (8, 'Most recent meeting',   '=IFERROR(MAX(c_Date),"")', 'dd-mmm-yy'),
    (8, 'Met in last 30 days',   '=COUNTIFS(c_Date,">="&TODAY()-30)', '#,##0'),
    (8, 'Overdue (>120 days)',   '=COUNTIF(c_Days,">120")', '#,##0'),
]
for i, (row, label, formula, fmt) in enumerate(MTILES):
    kpi(ms, row, KPI_COLS[i % 4], label, formula, fmt)
ms.cell(9, 2).font = font(13, True, NAVY)    # First meeting  (a date needs less room)
ms.cell(9, 5).font = font(13, True, NAVY)    # Most recent meeting

MON_R0 = 11
MONTHS = 18
section(ms, MON_R0, 'MEETING ACTIVITY BY MONTH', note=f'rolling {MONTHS} months')
table_header(ms, MON_R0 + 1, 2, ['Month', 'Contacts met', 'Cumulative (window)'], [12, 13, 15])
for i in range(MONTHS):
    r = MON_R0 + 2 + i
    band = i % 2 == 1
    if i == 0:
        body_cell(ms, r, 2, f'=EOMONTH(TODAY(),-{MONTHS})+1', 'mmm-yy', align='center', banded=band)
    else:
        body_cell(ms, r, 2, f'=EOMONTH($B{r - 1},0)+1', 'mmm-yy', align='center', banded=band)
    body_cell(ms, r, 3, f'=COUNTIFS(c_Date,">="&$B{r},c_Date,"<="&EOMONTH($B{r},0))', '#,##0', banded=band)
    body_cell(ms, r, 4, f'=$C{r}' if i == 0 else f'=$D{r - 1}+$C{r}', '#,##0', banded=band)
MON_RN = MON_R0 + 1 + MONTHS

FRM_R0 = MON_RN + 2
section(ms, FRM_R0, 'MEETING COVERAGE BY FIRM', note='which firms you have actually worked')
table_header(ms, FRM_R0 + 1, 2, ['Firm', 'Contacts', 'Met', 'Coverage', 'Meetings',
                                 'Last meeting', 'Days since', 'Attended an event'],
             [26, 10, 8, 10, 10, 13, 11, 13])
FIRMS_BY_MTG = sorted(FIRMS, key=lambda f_: (-sum(x['mtgs'] for x in rows if x['firm'] == f_), f_))
for i, f_ in enumerate(FIRMS_BY_MTG):
    r = FRM_R0 + 2 + i
    band = i % 2 == 1
    body_cell(ms, r, 2, f_, align='left', banded=band)
    body_cell(ms, r, 3, f'=COUNTIF(c_Firm,$B{r})', '#,##0', banded=band)
    body_cell(ms, r, 4, f'=COUNTIFS(c_Firm,$B{r},c_Met,"Yes")', '#,##0', banded=band)
    body_cell(ms, r, 5, f'=IFERROR($D{r}/$C{r},0)', '0.0%', banded=band)
    body_cell(ms, r, 6, f'=SUMIF(c_Firm,$B{r},c_Mtgs)', '#,##0', banded=band)
    body_cell(ms, r, 7, f'=IF(_xlfn.MAXIFS(c_Date,c_Firm,$B{r})=0,"",_xlfn.MAXIFS(c_Date,c_Firm,$B{r}))',
              'dd-mmm-yy', align='center', banded=band)
    body_cell(ms, r, 8, f'=IF($G{r}="","",TODAY()-$G{r})', '#,##0', banded=band)
    body_cell(ms, r, 9, f'=COUNTIFS(c_Firm,$B{r},c_EvtAtt,">0")', '#,##0', banded=band)
FRM_RN = FRM_R0 + 1 + len(FIRMS_BY_MTG)
ms.conditional_formatting.add(f'E{FRM_R0 + 2}:E{FRM_RN}',
                              ColorScaleRule(start_type='num', start_value=0, start_color='FFFFFF',
                                             end_type='num', end_value=1, end_color='8ED18E'))
ms.conditional_formatting.add(f'H{FRM_R0 + 2}:H{FRM_RN}',
                              CellIsRule(operator='greaterThan', formula=['120'],
                                         fill=fill(RED), font=font(10, True, REDT)))

FUP_R0 = FRM_RN + 2
NFUP = 15
section(ms, FUP_R0, 'OLDEST RELATIONSHIPS  —  FOLLOW UP FIRST',
        note='the contacts you have met whose last meeting is furthest in the past')
table_header(ms, FUP_R0 + 1, 2, ['Name', 'Firm', 'Last meeting', 'Days since',
                                 'Events attended', 'Invested?', 'Email'])
for i in range(NFUP):
    r = FUP_R0 + 2 + i
    band = i % 2 == 1
    ms.cell(r, 1, f'=IFERROR(MATCH({i + 1},c_FUp,0),"")').font = font(10, color='FFFFFF')
    body_cell(ms, r, 2, f'=IF($A{r}="","",INDEX(c_Name,$A{r}))', align='left', banded=band)
    body_cell(ms, r, 3, f'=IF($A{r}="","",INDEX(c_Firm,$A{r}))', align='left', banded=band)
    body_cell(ms, r, 4, f'=IF($A{r}="","",INDEX(c_Date,$A{r}))', 'dd-mmm-yy', align='center', banded=band)
    body_cell(ms, r, 5, f'=IF($A{r}="","",INDEX(c_Days,$A{r}))', '#,##0', align='center', banded=band)
    body_cell(ms, r, 6, f'=IF($A{r}="","",INDEX(c_EvtNames,$A{r})&"")', align='left', banded=band)
    body_cell(ms, r, 7, f'=IF($A{r}="","",INDEX(c_Invested,$A{r}))', align='center', banded=band)
    body_cell(ms, r, 8, f'=IF($A{r}="","",INDEX(c_Email,$A{r})&"")', align='left', banded=band)
set_widths(ms, {1: 3, 2: 26, 3: 20, 4: 15, 5: 12, 6: 22, 7: 14, 8: 30, 9: 16,
                10: 3, 11: 12, 12: 11, 13: 11})
ms.column_dimensions['A'].hidden = True

ch4 = BarChart()
ch4.type, ch4.style = 'col', 10
ch4.title = 'Contacts met per month'
ch4.add_data(Reference(ms, min_col=3, min_row=MON_R0 + 1, max_row=MON_RN), titles_from_data=True)
ch4.set_categories(Reference(ms, min_col=2, min_row=MON_R0 + 2, max_row=MON_RN))
ch4.height, ch4.width = 9, 16
ch4.legend = None
ms.add_chart(ch4, 'K12')

TOPM = min(10, len(FIRMS_BY_MTG))
ch5 = BarChart()
ch5.type, ch5.style = 'bar', 10
ch5.title = 'Meetings by firm (top 10)'
ch5.add_data(Reference(ms, min_col=6, min_row=FRM_R0 + 1, max_row=FRM_R0 + 1 + TOPM), titles_from_data=True)
ch5.set_categories(Reference(ms, min_col=2, min_row=FRM_R0 + 2, max_row=FRM_R0 + 1 + TOPM))
ch5.height, ch5.width = 9, 16
ch5.legend = None
ms.add_chart(ch5, f'K{FRM_R0 + 1}')

# =============================================================== CONTACTS
ct = wb.create_sheet('Contacts')
ct.sheet_properties.tabColor = 'BF8F00'
sheet_title(ct, 'CONTACT DIRECTORY',
            'Every contact, sorted by firm then name. Change any of the yellow filter boxes below and the list rebuilds instantly.', 14)

flt = [(2, 'Firm:', 3, '=f_Firm', '(All)'), (4, 'Met?:', 5, '=f_Met', '(All)'),
       (6, 'Attended:', 7, '=f_Event', '(All)'), (8, 'Warmth:', 9, '=f_Engage', '(All)'),
       (10, 'Search:', 11, None, '')]
for lab_col, lab, in_col, src, default in flt:
    l = ct.cell(3, lab_col, lab)
    l.font = font(10, True, NAVY)
    l.alignment = Alignment(horizontal='right', vertical='center')
    c = ct.cell(3, in_col, default)
    c.font = font(10, True, INPUT)
    c.fill = fill('FFF2CC')
    c.border = BOX
    c.alignment = Alignment(horizontal='left', vertical='center')
    if src:
        d = DataValidation(type='list', formula1=src, allow_blank=True, showErrorMessage=False)
        ct.add_data_validation(d)
        d.add(c)
ct.cell(3, 13, '=TEXT(COUNTIF(c_Pass,1),"#,##0")&" of "&TEXT(COUNTA(c_Name),"#,##0")&" contacts shown"').font = \
    font(10, True, BLUE)
ct.row_dimensions[3].height = 20

CT_HDR = 5
CT_R0 = 6
CH_ = ['Name', 'Firm', 'Type', 'Email', 'Met?', 'Last meeting', 'Days since', '# Mtgs',
       'Events attended', 'Invested?', 'AUM (S$)', 'Source', 'Notes']
table_header(ct, CT_HDR, 2, CH_)
set_widths(ct, {1: 3, 2: 24, 3: 20, 4: 15, 5: 30, 6: 7, 7: 12, 8: 10, 9: 8,
                10: 32, 11: 9, 12: 13, 13: 24, 14: 46})
COLMAP = ['c_Name', 'c_Firm', 'c_Type', 'c_Email', 'c_Met', 'c_Date', 'c_Days', 'c_Mtgs',
          'c_EvtNames', 'c_Invested', 'c_AUM', 'c_Source', 'c_Notes']
# columns land at B..N: Name C Firm D Type E Email F Met G Date H Days I Mtgs
#                       J Events K Invested L AUM M Source N Notes
FMT = {7: 'dd-mmm-yy', 8: '#,##0', 9: '0', 12: '#,##0'}
ALIGN = {6: 'center', 7: 'center', 8: 'center', 9: 'center', 11: 'center', 12: 'right'}
NUMERIC = {7, 8, 9, 12}          # an empty source cell must stay empty, not become a 0
for i in range(CONTACT_ROWS):
    r = CT_R0 + i
    ct.cell(r, 1, f'=IFERROR(MATCH(ROW()-{CT_R0 - 1},c_Seq,0),"")').font = font(10, color='FFFFFF')
    for j, rng in enumerate(COLMAP):
        col = 2 + j
        if col in NUMERIC:
            f_ = f'=IF($A{r}="","",IF(INDEX({rng},$A{r})="","",INDEX({rng},$A{r})))'
        else:
            f_ = f'=IF($A{r}="","",INDEX({rng},$A{r})&"")'
        c = ct.cell(r, col, f_)
        c.font = font(10)
        c.border = BOX
        c.alignment = Alignment(horizontal=ALIGN.get(col, 'left'), vertical='center')
        if col in FMT:
            c.number_format = FMT[col]
        if i % 2:
            c.fill = fill(BAND)
ct.column_dimensions['A'].hidden = True
ct.freeze_panes = 'B6'
ct.auto_filter.ref = f'B{CT_HDR}:N{CT_R0 + CONTACT_ROWS - 1}'

last_ct = CT_R0 + CONTACT_ROWS - 1
ct.conditional_formatting.add(f'F{CT_R0}:F{last_ct}',
                              CellIsRule(operator='equal', formula=['"Yes"'],
                                         fill=fill(GREEN), font=font(10, True, GREENT)))
ct.conditional_formatting.add(f'H{CT_R0}:H{last_ct}',
                              CellIsRule(operator='greaterThan', formula=['120'],
                                         fill=fill(RED), font=font(10, True, REDT)))
ct.conditional_formatting.add(f'K{CT_R0}:K{last_ct}',
                              CellIsRule(operator='equal', formula=['"Yes"'],
                                         fill=fill(GREEN), font=font(10, True, GREENT)))

# ================================================= keep the original sheets
src = openpyxl.load_workbook(SRC := 'source.xlsx', data_only=True)
for nm in ['Meeting List', 'Attendance', 'Branch Directors', 'Mass Email PIAS', 'ILP Data', 'Goodies']:
    s_ = src[nm]
    t = wb.create_sheet(f'Src – {nm}'[:31])
    t.sheet_properties.tabColor = 'BFBFBF'
    for row in s_.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            v = cell.value
            if isinstance(v, str) and v.startswith('#'):
                v = None                      # drop pre-existing error values
            nc = t.cell(cell.row, cell.column, v)
            nc.font = font(10, cell.row == 1)
            if isinstance(v, datetime.datetime):
                nc.number_format = 'dd-mmm-yy'
    for col in range(1, (s_.max_column or 1) + 1):
        t.column_dimensions[get_column_letter(col)].width = 20
    t.cell(1, (s_.max_column or 1) + 2, 'ORIGINAL DATA — kept for reference, not used by any formula').font = \
        font(9, True, REDT)
    t.freeze_panes = 'A2'

wb.move_sheet('Setup', offset=len(wb.sheetnames) - 1)   # Setup to the back, in front of Src sheets
order = ['Dashboard', 'Meeting Stats', 'Contacts', 'RawData', 'Setup'] + \
        [n for n in wb.sheetnames if n.startswith('Src')]
wb._sheets = [wb[n] for n in order]
wb.active = 0

from openpyxl.worksheet.properties import PageSetupProperties
PRINT = {'Dashboard': f'A1:K{ENG_R0 + 8}', 'Meeting Stats': f'A1:I{FUP_R0 + 1 + NFUP}',
         'Contacts': f'A1:N{CT_R0 + 80}', 'Setup': 'A1:K45'}
for nm, area in PRINT.items():
    ws = wb[nm]
    ws.print_area = area
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = f'{CT_HDR}:{CT_HDR}' if nm == 'Contacts' else None

wb.save('IFA_Contacts_Dashboard.xlsx')
print('written; firms:', len(FIRMS), 'contacts:', len(rows))
print('firm rows', FIRM_R0 + 1, '-', FIRM_RN, 'total', TOT_R, 'events', EV_R0, 'eng', ENG_R0)
print('ms: months', MON_R0, 'firms', FRM_R0, 'fup', FUP_R0)
