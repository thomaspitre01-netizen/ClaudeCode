Attribute VB_Name = "IFA_Contacts"
'==============================================================================
' IFA CONTACT DATABASE - optional macros
'
' The workbook works entirely on formulas; these are convenience buttons only.
'
' TO INSTALL:
'   1. Open IFA_Contacts_Dashboard.xlsx
'   2. File > Save As > Excel Macro-Enabled Workbook (*.xlsm)
'   3. Press ALT+F11, then File > Import File... and pick this .bas
'   4. Back in Excel: ALT+F8 lists the macros below
'==============================================================================
Option Explicit

Private Const SH_RAW As String = "RawData"
Private Const SH_SET As String = "Setup"
Private Const FIRST_ROW As Long = 2
Private Const COL_NAME As Long = 2          ' B
Private Const COL_FIRM As Long = 4          ' D
Private Const COL_NOTES As Long = 19        ' S  - last column you type into
Private Const COL_LASTAUTO As Long = 28     ' AB - last calculated column


'--- last used row of the contact table -------------------------------------
Private Function LastContactRow() As Long
    With Sheets(SH_RAW)
        LastContactRow = .Cells(.Rows.Count, COL_NAME).End(xlUp).Row
        If LastContactRow < FIRST_ROW Then LastContactRow = FIRST_ROW - 1
    End With
End Function

'--- how far the calculated columns are filled down --------------------------
Private Function FormulaRow() As Long
    With Sheets(SH_RAW)
        FormulaRow = .Cells(.Rows.Count, COL_LASTAUTO).End(xlUp).Row
    End With
End Function


'==============================================================================
' AddContact - guided prompt, writes one new row and copies the formulas down
'==============================================================================
Public Sub AddContact()
    Dim ws As Worksheet, r As Long, nm As String
    Set ws = Sheets(SH_RAW)

    nm = Trim(InputBox("Full name of the new contact:", "Add contact"))
    If nm = "" Then Exit Sub

    If Not IsEmpty(Application.Match(nm, ws.Columns(COL_NAME), 0)) Then
        If Not IsError(Application.Match(nm, ws.Columns(COL_NAME), 0)) Then
            If MsgBox(nm & " already exists. Add anyway?", vbYesNo + vbQuestion) = vbNo Then Exit Sub
        End If
    End If

    r = LastContactRow + 1
    Application.ScreenUpdating = False

    ' make sure the calculated columns reach this row
    If FormulaRow < r Then
        ws.Range(ws.Cells(r - 1, COL_NOTES + 1), ws.Cells(r - 1, COL_LASTAUTO)).Copy
        ws.Range(ws.Cells(r, COL_NOTES + 1), ws.Cells(r, COL_LASTAUTO)).PasteSpecial xlPasteAll
        ws.Cells(r, 1).Value = ws.Cells(r - 1, 1).Value      ' ID formula
        ws.Cells(r - 1, 1).Copy ws.Cells(r, 1)
        Application.CutCopyMode = False
    End If

    ws.Cells(r, COL_NAME).Value = nm
    ws.Cells(r, COL_FIRM).Value = InputBox("Firm (must match the Setup > Firms list):", "Add contact")
    ws.Cells(r, 5).Value = "Adviser"
    ws.Cells(r, 6).Value = "Other"
    ws.Cells(r, 7).Value = "No"
    ws.Cells(r, 10).Value = "No"
    Dim i As Long
    For i = 14 To 18                                          ' N..R event columns
        If ws.Cells(r, i).Value = "" Then ws.Cells(r, i).Value = "Not Invited"
    Next i

    Application.ScreenUpdating = True
    ws.Activate
    ws.Cells(r, 3).Select                                     ' land on Email
    MsgBox "Row " & r & " added. Fill in the remaining white cells.", vbInformation
End Sub


'==============================================================================
' SortContacts - re-sorts RawData by Firm then Name (run after adding rows)
'==============================================================================
Public Sub SortContacts()
    Dim ws As Worksheet, lr As Long
    Set ws = Sheets(SH_RAW)
    lr = LastContactRow
    If lr < FIRST_ROW + 1 Then Exit Sub

    Application.ScreenUpdating = False
    With ws.Sort
        .SortFields.Clear
        .SortFields.Add Key:=ws.Range(ws.Cells(FIRST_ROW, COL_FIRM), ws.Cells(lr, COL_FIRM)), Order:=xlAscending
        .SortFields.Add Key:=ws.Range(ws.Cells(FIRST_ROW, COL_NAME), ws.Cells(lr, COL_NAME)), Order:=xlAscending
        .SetRange ws.Range(ws.Cells(FIRST_ROW, 1), ws.Cells(lr, COL_NOTES))
        .Header = xlNo
        .Apply
    End With
    Application.ScreenUpdating = True
    MsgBox "Sorted " & (lr - FIRST_ROW + 1) & " contacts by firm, then name.", vbInformation
End Sub


'==============================================================================
' ExtendCapacity - grows the table and every c_* range by n rows
'==============================================================================
Public Sub ExtendCapacity()
    Dim ws As Worksheet, newLast As Long, oldLast As Long, extra As Variant
    Dim nm As Name, ref As String, i As Long
    Set ws = Sheets(SH_RAW)

    extra = Application.InputBox("Add how many extra contact rows?", "Extend capacity", 200, Type:=1)
    If VarType(extra) = vbBoolean Then Exit Sub

    oldLast = FormulaRow
    newLast = oldLast + CLng(extra)

    Application.ScreenUpdating = False
    ' copy the whole formula row down
    ws.Rows(oldLast).Copy
    ws.Rows(oldLast + 1 & ":" & newLast).PasteSpecial xlPasteAll
    Application.CutCopyMode = False
    ' clear the typed columns on the new rows, keep the calculated ones
    ws.Range(ws.Cells(oldLast + 1, COL_NAME), ws.Cells(newLast, COL_NOTES)).ClearContents

    ' repoint every named range that ends at the old last row
    For Each nm In ThisWorkbook.Names
        If Left$(nm.Name, 2) = "c_" Then
            ref = nm.RefersTo
            nm.RefersTo = Replace(ref, "$" & oldLast, "$" & newLast)
        End If
    Next nm

    ws.AutoFilterMode = False
    ws.Range(ws.Cells(1, 1), ws.Cells(newLast, 24)).AutoFilter
    Application.ScreenUpdating = True
    MsgBox "Capacity is now " & (newLast - 1) & " contacts." & vbCrLf & _
           "Add the same number of display rows to the Contacts tab if you want to see them all there.", vbInformation
End Sub


'==============================================================================
' FindDuplicates - lists contacts sharing a name or an email address
'==============================================================================
Public Sub FindDuplicates()
    Dim ws As Worksheet, r As Long, lr As Long, msg As String, n As Long
    Dim seen As Object: Set seen = CreateObject("Scripting.Dictionary")
    Dim k As String
    Set ws = Sheets(SH_RAW)
    lr = LastContactRow

    For r = FIRST_ROW To lr
        k = LCase$(Replace(Trim$(CStr(ws.Cells(r, COL_NAME).Value)), " ", ""))
        If k <> "" Then
            If seen.Exists(k) Then
                n = n + 1
                If n <= 25 Then msg = msg & vbCrLf & "row " & r & "  " & ws.Cells(r, COL_NAME).Value & _
                                        "  (also row " & seen(k) & ")"
            Else
                seen(k) = r
            End If
        End If
    Next r

    If n = 0 Then
        MsgBox "No duplicate names found in " & (lr - 1) & " contacts.", vbInformation
    Else
        MsgBox n & " possible duplicate(s):" & vbCrLf & msg, vbExclamation
    End If
End Sub


'==============================================================================
' GoToContact - jump from anywhere to a contact's row in RawData
'==============================================================================
Public Sub GoToContact()
    Dim nm As String, hit As Variant
    nm = Trim(InputBox("Name to find (exact):", "Go to contact"))
    If nm = "" Then Exit Sub
    hit = Application.Match(nm, Sheets(SH_RAW).Columns(COL_NAME), 0)
    If IsError(hit) Then
        MsgBox nm & " is not in the database.", vbExclamation
    Else
        Sheets(SH_RAW).Activate
        Sheets(SH_RAW).Cells(CLng(hit), COL_NAME).Select
    End If
End Sub


'==============================================================================
' ResetFilters - put the Contacts tab back to "show everything"
'==============================================================================
Public Sub ResetFilters()
    With Sheets("Contacts")
        .Range("C3").Value = "(All)"
        .Range("E3").Value = "(All)"
        .Range("G3").Value = "(All)"
        .Range("I3").Value = "(All)"
        .Range("K3").ClearContents
        .Activate
    End With
End Sub
