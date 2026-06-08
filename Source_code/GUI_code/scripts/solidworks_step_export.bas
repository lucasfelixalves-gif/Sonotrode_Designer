 Option Explicit



' SolidWorks STEP batch exporter (3D workflow).

' - Reads design table rows from workbook paired with active part.

' - Exports one STEP per configuration row.

' - Handles native SolidWorks design table layout:

'   row 1 title, row 2 headers, column A configuration names.



Private Const SW_DOC_PART As Long = 1

Private Const SW_SAVE_AS_CURRENT_VERSION As Long = 0

Private Const SW_SAVE_AS_OPTIONS_SILENT As Long = 1

Private Const SW_PREF_STEP_EXPORT_FORMAT As Long = 274

Private Const SW_STEP_AP214 As Long = 214



' Leave blank to auto-detect geometry/design table sheet.

Private Const GEOMETRY_SHEET_NAME As String = ""



' Leave blank to use <project>\models\

Private Const EXPORT_FOLDER_OVERRIDE As String = ""



' Leave blank to use <part-folder>\<part-name>.xlsx

Private Const WORKBOOK_PATH_OVERRIDE As String = ""



Private swApp As Object

Private swModel As Object



Public Sub main()

    Dim partPath As String

    Dim workbookPath As String

    Dim defaultExportFolder As String

    Dim exportFolder As String

    Dim excelApp As Object

    Dim workbook As Object

    Dim sheet As Object

    Dim headerMap As Object

    Dim knownConfigs As Object

    Dim usedFileNames As Object



    Dim headerRow As Long

    Dim configColumn As Long

    Dim modelNameColumn As Long

    Dim enabledColumn As Long

    Dim lastRow As Long



    Dim rowIndex As Long

    Dim configRaw As String

    Dim configName As String

    Dim rawModelName As String

    Dim finalModelName As String

    Dim stepPath As String

    Dim saveErrors As Long

    Dim saveWarnings As Long

    Dim saveOk As Boolean



    Dim exportedCount As Long

    Dim skippedCount As Long

    Dim errorCount As Long

    Dim logText As String



    On Error GoTo FatalError



    Set swApp = Application.SldWorks
    exportFolder = defaultExportFolder
    Set swModel = swApp.ActiveDoc



    If swModel Is Nothing Then

        MsgBox "Please open a SolidWorks part first.", vbCritical, "STEP Export"

        Exit Sub

    End If



    If swModel.GetType <> SW_DOC_PART Then

        MsgBox "The active SolidWorks document must be a part.", vbCritical, "STEP Export"

        Exit Sub

    End If



    partPath = Trim$(CStr(swModel.GetPathName))

    If Len(partPath) = 0 Then

        MsgBox "Save the part before running the export macro.", vbCritical, "STEP Export"

        Exit Sub

    End If



    ' --- 1. Start Excel early so we can use its file picker dialog ---

    Set excelApp = CreateObject("Excel.Application")

    ConfigureExcelApp excelApp



    ' --- 2. Pass both the CAD path AND the Excel app to the resolver ---

    workbookPath = ResolveWorkbookPath(partPath, excelApp)



    ' --- 3. If the user hits cancel on the file picker, stop gracefully ---

    If Len(workbookPath) = 0 Then

        MsgBox "STEP export cancelled. Master Workbook is required.", vbInformation, "STEP Export"

        GoTo CleanExit

    End If



    defaultExportFolder = ResolveExportFolder(workbookPath)

    exportFolder = defaultExportFolder



    If Len(exportFolder) = 0 Then

        MsgBox "STEP export cancelled by user.", vbInformation, "STEP Export"

        GoTo CleanExit

    End If



    EnsureFolderExists exportFolder



    ' --- 4. Open the workbook now that we know exactly where it is ---

    Set workbook = excelApp.Workbooks.Open(workbookPath, False, True)

    Set sheet = ResolveGeometrySheet(workbook, GEOMETRY_SHEET_NAME)



    headerRow = DetectHeaderRow(sheet)

    If headerRow <= 0 Then

        Err.Raise vbObjectError + 1005, , "Could not detect a configuration header row in sheet: " & sheet.Name

    End If



    Set headerMap = BuildHeaderMap(sheet, headerRow)

    configColumn = FindConfigurationColumn(sheet, headerMap, headerRow)

    modelNameColumn = GetOptionalColumnIndex(headerMap, "model_name")

    enabledColumn = GetOptionalColumnIndex(headerMap, "enabled")



    If configColumn = 0 And IsLikelyConfigurationColumn(sheet, headerRow, 1) Then

        configColumn = 1

    End If



    If configColumn = 0 Then
        Err.Raise vbObjectError + 1004, , _
            "No configuration source found. Add a Configuration column (or $CONFIGURATION), " & _
            "or keep configuration names in column A."
    End If



    lastRow = LastUsedRow(sheet, configColumn)

    If lastRow < headerRow + 1 Then

        Err.Raise vbObjectError + 1000, , "The geometry sheet has no data rows to export."

    End If



    Set knownConfigs = BuildConfigurationMap(swModel)

    Set usedFileNames = CreateObject("Scripting.Dictionary")



    swApp.SetUserPreferenceIntegerValue SW_PREF_STEP_EXPORT_FORMAT, SW_STEP_AP214



    For rowIndex = headerRow + 1 To lastRow

        configRaw = Trim$(CStr(sheet.Cells(rowIndex, configColumn).value))

        If Len(configRaw) = 0 Then

            skippedCount = skippedCount + 1

            GoTo NextRow

        End If



        configName = ResolveConfigurationName(configRaw, knownConfigs)

        If Len(configName) = 0 Then

            skippedCount = skippedCount + 1

            logText = logText & "[SKIP] Row " & rowIndex & ": default row ignored." & vbCrLf

            GoTo NextRow

        End If



        If enabledColumn > 0 Then

            If Not IsTruthy(sheet.Cells(rowIndex, enabledColumn).value) Then

                skippedCount = skippedCount + 1

                GoTo NextRow

            End If

        End If



        rawModelName = configName

        If modelNameColumn > 0 Then

            rawModelName = Trim$(CStr(sheet.Cells(rowIndex, modelNameColumn).value))

            If Len(rawModelName) = 0 Then rawModelName = configName

        End If



        finalModelName = MakeUniqueFileStem(SanitizeFileStem(rawModelName), usedFileNames)

        stepPath = exportFolder & finalModelName & ".step"

        If FileExists(stepPath) Then

            skippedCount = skippedCount + 1

            logText = logText & "[SKIPPED] " & configName & " -> " & finalModelName & ".step already exists." & vbCrLf

            GoTo NextRow

        End If



        If swModel.ShowConfiguration2(configName) = False Then

            errorCount = errorCount + 1

            logText = logText & "[ERROR] Row " & rowIndex & ": configuration not found -> " & configName & vbCrLf

            GoTo NextRow

        End If



        swModel.ForceRebuild3 False



        If FileExists(stepPath) Then Kill stepPath



        saveErrors = 0

        saveWarnings = 0

        saveOk = swModel.Extension.SaveAs3(stepPath, SW_SAVE_AS_CURRENT_VERSION, SW_SAVE_AS_OPTIONS_SILENT, Nothing, Nothing, saveErrors, saveWarnings)



        If saveOk And saveErrors = 0 And FileExists(stepPath) Then

            exportedCount = exportedCount + 1

            logText = logText & "[OK] " & configName & " -> " & finalModelName & ".step" & vbCrLf

        Else

            errorCount = errorCount + 1

            logText = logText & "[ERROR] " & configName & " -> export failed (errors=" & saveErrors & ", warnings=" & saveWarnings & ")" & vbCrLf

        End If



NextRow:

    Next rowIndex



    MsgBox _
        "STEP batch export complete." & vbCrLf & vbCrLf & _
        "Workbook: " & workbookPath & vbCrLf & _
        "Sheet: " & sheet.Name & vbCrLf & _
        "Output folder: " & exportFolder & vbCrLf & vbCrLf & _
        "Exported: " & exportedCount & vbCrLf & _
        "Skipped: " & skippedCount & vbCrLf & _
        "Errors: " & errorCount & vbCrLf & vbCrLf & _
        logText, _
        IIf(errorCount = 0, vbInformation, vbExclamation), _
        "STEP Export"



CleanExit:

    On Error Resume Next

    If Not workbook Is Nothing Then workbook.Close False

    If Not excelApp Is Nothing Then excelApp.Quit

    Set sheet = Nothing

    Set workbook = Nothing

    Set excelApp = Nothing

    Set usedFileNames = Nothing

    Set knownConfigs = Nothing

    Set headerMap = Nothing

    Set swModel = Nothing

    Set swApp = Nothing

    Exit Sub



FatalError:

    MsgBox "STEP export failed: " & Err.Description, vbCritical, "STEP Export"

    Resume CleanExit

End Sub



Private Function ResolveWorkbookPath(ByVal partPath As String, ByVal excelApp As Object) As String

    Dim folderPath As String

    Dim partFolder As String

    Dim parentFolder As String

    Dim configFolder As String

    Dim baseName As String

    Dim workbookPath As String

    Dim candidatePath As String

    Dim bestWorkbookPath As String

    Dim fileItem As Object

    Dim pickedFile As Variant

    Dim fso As Object



    Set fso = CreateObject("Scripting.FileSystemObject")



    ' Step 1: explicit override path

    If Len(Trim$(WORKBOOK_PATH_OVERRIDE)) > 0 Then

        workbookPath = Trim$(WORKBOOK_PATH_OVERRIDE)

        If fso.FileExists(workbookPath) Then

            ResolveWorkbookPath = workbookPath

            Exit Function

        End If

    End If



    ' Step 2: same folder + same basename as CAD part

    folderPath = Left$(partPath, InStrRev(partPath, "\"))

    partFolder = Left$(partPath, InStrRev(partPath, "\") - 1)

    baseName = Mid$(partPath, InStrRev(partPath, "\") + 1)

    baseName = Left$(baseName, InStrRev(baseName, ".") - 1)

    workbookPath = folderPath & baseName & ".xlsx"



    If fso.FileExists(workbookPath) Then

        ResolveWorkbookPath = workbookPath

        Exit Function

    End If



    ' Step 3: search common 01_master_config locations.

    configFolder = ""

    If InStrRev(partFolder, "\") > 0 Then

        parentFolder = Left$(partFolder, InStrRev(partFolder, "\") - 1)

    Else

        parentFolder = ""

    End If



    If LCase$(Mid$(partFolder, InStrRev(partFolder, "\") + 1)) = "01_master_config" Then

        configFolder = partFolder

    Else

        candidatePath = partFolder & "\01_Master_Config"
        If fso.FolderExists(candidatePath) Then configFolder = candidatePath

        If Len(configFolder) = 0 Then
            candidatePath = partFolder & "\01_master_config"
            If fso.FolderExists(candidatePath) Then configFolder = candidatePath
        End If

        If Len(configFolder) = 0 And Len(parentFolder) > 0 Then
            candidatePath = parentFolder & "\01_Master_Config"
            If fso.FolderExists(candidatePath) Then configFolder = candidatePath
        End If

        If Len(configFolder) = 0 And Len(parentFolder) > 0 Then
            candidatePath = parentFolder & "\01_master_config"
            If fso.FolderExists(candidatePath) Then configFolder = candidatePath
        End If

    End If



    If Len(configFolder) > 0 Then

        candidatePath = configFolder & "\" & baseName & ".xlsx"

        If fso.FileExists(candidatePath) Then

            ResolveWorkbookPath = candidatePath

            Exit Function

        End If



        bestWorkbookPath = ""

        For Each fileItem In fso.GetFolder(configFolder).Files

            If LCase$(Right$(CStr(fileItem.Name), 5)) = ".xlsx" Then

                If Len(bestWorkbookPath) = 0 Then bestWorkbookPath = CStr(fileItem.Path)

                If InStr(1, LCase$(CStr(fileItem.Name)), "master", vbTextCompare) > 0 Then

                    bestWorkbookPath = CStr(fileItem.Path)

                    Exit For

                End If

            End If

        Next fileItem



        If Len(bestWorkbookPath) > 0 Then

            ResolveWorkbookPath = bestWorkbookPath

            Exit Function

        End If

    End If



    ' Step 4: warn user

    MsgBox _
        "Master workbook could not be found automatically." & vbCrLf & vbCrLf & _
        "Checked default: " & workbookPath, _
        vbExclamation, _
        "STEP Export"



    ' Step 5: show Excel for picker

    excelApp.Visible = True



    ' Step 6: force manual selection

    pickedFile = excelApp.GetOpenFileName("Excel Workbooks (*.xlsx), *.xlsx", 1, "Select Master Workbook")



    ' Step 7: hide Excel and return result

    excelApp.Visible = False

    If VarType(pickedFile) = vbBoolean And pickedFile = False Then

        ResolveWorkbookPath = ""

    Else

        ResolveWorkbookPath = CStr(pickedFile)

    End If

End Function



Private Function ResolveExportFolder(ByVal workbookPath As String) As String

    Dim workbookFolder As String

    Dim parentFolder As String

    Dim exportFolder As String

    Dim fso As Object



    If Len(Trim$(EXPORT_FOLDER_OVERRIDE)) > 0 Then

        exportFolder = EXPORT_FOLDER_OVERRIDE

    Else

        workbookFolder = Left$(workbookPath, InStrRev(workbookPath, "\") - 1)

        If InStrRev(workbookFolder, "\") > 0 Then
            parentFolder = Left$(workbookFolder, InStrRev(workbookFolder, "\") - 1)
        Else
            parentFolder = ""
        End If

        ' Prefer exact project naming first.
        If Len(parentFolder) > 0 Then
            exportFolder = FindExistingStepFolder(parentFolder)
        End If

        If Len(exportFolder) = 0 Then
            exportFolder = FindExistingStepFolder(workbookFolder)
        End If

        If Len(exportFolder) = 0 Then

            If Len(parentFolder) > 0 Then
                exportFolder = parentFolder & "\02_Geometry_STEP"
            Else
                exportFolder = workbookFolder & "\02_Geometry_STEP"
            End If

        End If

    End If



    exportFolder = EnsureTrailingBackslash(exportFolder)



    Set fso = CreateObject("Scripting.FileSystemObject")

    If Not fso.FolderExists(exportFolder) Then

        MsgBox "Could not find: " & exportFolder & vbCrLf & vbCrLf & _
            "Please select the export folder for STEP files.", vbExclamation, "STEP Export"

        exportFolder = PromptExportFolder(exportFolder)

        If Len(exportFolder) = 0 Then

            ResolveExportFolder = ""

            Exit Function

        End If

    End If



    ResolveExportFolder = exportFolder

End Function



Private Function FindExistingStepFolder(ByVal targetRoot As String) As String

    Dim fso As Object

    Dim candidatePath As String

    Dim subFolder As Object

    Dim folderName As String



    Set fso = CreateObject("Scripting.FileSystemObject")

    If Not fso.FolderExists(targetRoot) Then Exit Function



    candidatePath = targetRoot & "\02_Geometry_STEP"
    If fso.FolderExists(candidatePath) Then
        FindExistingStepFolder = candidatePath
        Exit Function
    End If

    candidatePath = targetRoot & "\02_step"
    If fso.FolderExists(candidatePath) Then
        FindExistingStepFolder = candidatePath
        Exit Function
    End If

    candidatePath = targetRoot & "\02_steps"
    If fso.FolderExists(candidatePath) Then
        FindExistingStepFolder = candidatePath
        Exit Function
    End If



    For Each subFolder In fso.GetFolder(targetRoot).SubFolders

        folderName = LCase$(CStr(subFolder.Name))

        If Left$(folderName, 2) = "02" And InStr(1, folderName, "step", vbTextCompare) > 0 Then
            FindExistingStepFolder = CStr(subFolder.Path)
            Exit Function
        End If

    Next subFolder

End Function



Private Function PromptExportFolder(ByVal defaultFolder As String) As String

    Dim shellApp As Object

    Dim selectedFolder As Object

    Dim selectedPath As String



    On Error GoTo FolderPromptError



    Set shellApp = CreateObject("Shell.Application")



    ' 64 + 1 => modern dialog with file-system folders only.

    Set selectedFolder = shellApp.BrowseForFolder(0, _
        "Choose destination folder for STEP exports:", _
        65, _
        defaultFolder)



    If selectedFolder Is Nothing Then

        PromptExportFolder = ""

        Exit Function

    End If



    selectedPath = CStr(selectedFolder.Self.Path)

    If Len(Trim$(selectedPath)) = 0 Then

        PromptExportFolder = ""

    Else

        PromptExportFolder = EnsureTrailingBackslash(selectedPath)

    End If

    Exit Function



FolderPromptError:

    ' Fallback when folder picker is unavailable in host context.

    selectedPath = InputBox("Enter destination folder for STEP exports:", "STEP Export", defaultFolder)

    If Len(Trim$(selectedPath)) = 0 Then

        PromptExportFolder = ""

    Else

        PromptExportFolder = EnsureTrailingBackslash(selectedPath)

    End If

End Function



Private Function ResolveGeometrySheet(ByVal workbook As Object, ByVal requestedName As String) As Object

    Dim sheet As Object

    Dim fallbackSheet As Object



    If Len(Trim$(requestedName)) > 0 Then

        On Error Resume Next

        Set ResolveGeometrySheet = workbook.Worksheets(requestedName)

        On Error GoTo 0

        If ResolveGeometrySheet Is Nothing Then

            Err.Raise vbObjectError + 1002, , "Geometry sheet not found: " & requestedName

        End If

        Exit Function

    End If



    For Each sheet In workbook.Worksheets

        If Not IsSimulationSheet(CStr(sheet.Name)) Then

            If DetectHeaderRow(sheet) > 0 Then

                Set ResolveGeometrySheet = sheet

                Exit Function

            End If

            If fallbackSheet Is Nothing Then Set fallbackSheet = sheet

        End If

    Next sheet



    If Not fallbackSheet Is Nothing Then

        Set ResolveGeometrySheet = fallbackSheet

        Exit Function

    End If



    Err.Raise vbObjectError + 1003, , "Could not auto-detect the geometry sheet."

End Function



Private Function DetectHeaderRow(ByVal sheet As Object) As Long

    Dim rowIndex As Long

    Dim lastColumn As Long

    Dim columnIndex As Long

    Dim headerText As String

    Dim normalized As String



    For rowIndex = 1 To 20

        lastColumn = sheet.Cells(rowIndex, sheet.Columns.Count).End(-4159).Column

        If lastColumn <= 0 Then GoTo NextRow



        For columnIndex = 1 To lastColumn

            headerText = Trim$(CStr(sheet.Cells(rowIndex, columnIndex).value))

            normalized = NormalizeHeader(headerText)

            If IsConfigurationHeader(normalized, headerText) Or normalized = "model_name" Or IsLikelyDesignTableHeader(headerText) Then

                DetectHeaderRow = rowIndex

                Exit Function

            End If

        Next columnIndex

NextRow:

    Next rowIndex



    DetectHeaderRow = 0

End Function



Private Function BuildHeaderMap(ByVal sheet As Object, ByVal headerRow As Long) As Object

    Dim headerMap As Object

    Dim lastColumn As Long

    Dim columnIndex As Long

    Dim headerText As String

    Dim normalized As String



    Set headerMap = CreateObject("Scripting.Dictionary")

    lastColumn = sheet.Cells(headerRow, sheet.Columns.Count).End(-4159).Column



    For columnIndex = 1 To lastColumn

        headerText = Trim$(CStr(sheet.Cells(headerRow, columnIndex).value))

        normalized = NormalizeHeader(headerText)

        If Len(normalized) > 0 Then

            If Not headerMap.Exists(normalized) Then headerMap.Add normalized, columnIndex

        End If

    Next columnIndex



    Set BuildHeaderMap = headerMap

End Function



Private Function FindConfigurationColumn(ByVal sheet As Object, ByVal headerMap As Object, ByVal headerRow As Long) As Long

    Dim lastColumn As Long

    Dim columnIndex As Long

    Dim headerText As String

    Dim normalized As String



    If headerMap.Exists("configuration") Then

        FindConfigurationColumn = CLng(headerMap("configuration"))

        Exit Function

    End If



    If headerMap.Exists("config_name") Then

        FindConfigurationColumn = CLng(headerMap("config_name"))

        Exit Function

    End If



    lastColumn = sheet.Cells(headerRow, sheet.Columns.Count).End(-4159).Column

    For columnIndex = 1 To lastColumn

        headerText = Trim$(CStr(sheet.Cells(headerRow, columnIndex).value))

        normalized = NormalizeHeader(headerText)

        If IsConfigurationHeader(normalized, headerText) Then

            FindConfigurationColumn = columnIndex

            Exit Function

        End If

    Next columnIndex



    FindConfigurationColumn = 0

End Function



Private Function IsLikelyConfigurationColumn(ByVal sheet As Object, ByVal headerRow As Long, ByVal columnIndex As Long) As Boolean

    Dim rowIndex As Long

    Dim valueText As String

    Dim checked As Long



    For rowIndex = headerRow + 1 To headerRow + 30

        valueText = Trim$(CStr(sheet.Cells(rowIndex, columnIndex).value))

        If Len(valueText) = 0 Then

            If checked > 0 Then Exit For

            GoTo NextRow

        End If



        checked = checked + 1



        If LCase$(valueText) = "default" Then

            IsLikelyConfigurationColumn = True

            Exit Function

        End If



        If Not IsNumeric(valueText) And checked >= 2 Then

            IsLikelyConfigurationColumn = True

            Exit Function

        End If

NextRow:

    Next rowIndex



    IsLikelyConfigurationColumn = False

End Function



Private Function IsLikelyDesignTableHeader(ByVal rawHeader As String) As Boolean

    Dim text As String



    text = Trim$(rawHeader)

    If Len(text) = 0 Then

        IsLikelyDesignTableHeader = False

        Exit Function

    End If



    IsLikelyDesignTableHeader = (InStr(1, text, "@", vbTextCompare) > 0)

End Function



Private Function IsConfigurationHeader(ByVal normalizedHeader As String, ByVal rawHeader As String) As Boolean

    Dim rawLower As String



    rawLower = LCase$(Trim$(rawHeader))

    IsConfigurationHeader = _
        (normalizedHeader = "configuration") Or _
        (normalizedHeader = "config_name") Or _
        (normalizedHeader = "$configuration") Or _
        (InStr(1, rawLower, "$configuration", vbTextCompare) > 0) Or _
        (InStr(1, normalizedHeader, "configuration", vbTextCompare) > 0)

End Function



Private Function BuildConfigurationMap(ByVal swModel As Object) As Object

    Dim names As Variant

    Dim i As Long

    Dim cfg As String

    Dim dict As Object



    Set dict = CreateObject("Scripting.Dictionary")

    names = swModel.GetConfigurationNames



    If IsEmpty(names) Then

        Err.Raise vbObjectError + 1006, , "No configurations found in the active SolidWorks part."

    End If



    For i = LBound(names) To UBound(names)

        cfg = Trim$(CStr(names(i)))

        If Len(cfg) > 0 Then

            If Not dict.Exists(LCase$(cfg)) Then dict.Add LCase$(cfg), cfg

        End If

    Next i



    Set BuildConfigurationMap = dict

End Function



Private Function ResolveConfigurationName(ByVal requestedName As String, ByVal configMap As Object) As String

    Dim key As String



    key = LCase$(Trim$(requestedName))

    If Len(key) = 0 Then

        ResolveConfigurationName = ""

        Exit Function

    End If



    If configMap.Exists(key) Then

        ResolveConfigurationName = CStr(configMap(key))

        Exit Function

    End If



    If IsDefaultAlias(key) Then

        If configMap.Exists("default") Then

            ResolveConfigurationName = CStr(configMap("default"))

        Else

            ResolveConfigurationName = ""

        End If

        Exit Function

    End If



    ResolveConfigurationName = requestedName

End Function



Private Function IsDefaultAlias(ByVal value As String) As Boolean

    Dim text As String



    text = LCase$(Trim$(value))

    IsDefaultAlias = _
        (text = "default") Or _
        (text = "padrao") Or _
        (text = "standard") Or _
        (text = "std")

End Function



Private Function GetOptionalColumnIndex(ByVal headerMap As Object, ByVal normalizedHeader As String) As Long

    If headerMap.Exists(normalizedHeader) Then

        GetOptionalColumnIndex = CLng(headerMap(normalizedHeader))

    Else

        GetOptionalColumnIndex = 0

    End If

End Function



Private Function LastUsedRow(ByVal sheet As Object, ByVal columnIndex As Long) As Long

    LastUsedRow = sheet.Cells(sheet.Rows.Count, columnIndex).End(-4162).Row

End Function



Private Function NormalizeHeader(ByVal value As String) As String

    Dim text As String



    text = LCase$(Trim$(value))

    text = Replace(text, " ", "_")

    text = Replace(text, "-", "_")

    NormalizeHeader = text

End Function



Private Function IsTruthy(ByVal value As Variant) As Boolean

    Dim text As String



    If IsEmpty(value) Or IsNull(value) Then

        IsTruthy = False

        Exit Function

    End If



    Select Case VarType(value)

        Case vbBoolean

            IsTruthy = CBool(value)

        Case vbByte, vbInteger, vbLong, vbSingle, vbDouble, vbCurrency

            IsTruthy = (CDbl(value) <> 0)

        Case Else

            text = LCase$(Trim$(CStr(value)))

            IsTruthy = (text = "true") Or (text = "t") Or (text = "yes") Or (text = "y") Or (text = "1") Or (text = "enabled")

    End Select

End Function



Private Function SanitizeFileStem(ByVal rawValue As String) As String

    Dim invalidChars As Variant

    Dim i As Long

    Dim cleaned As String



    cleaned = Trim$(rawValue)

    invalidChars = Array("<", ">", ":", Chr$(34), "/", "\", "|", "?", "*")



    For i = LBound(invalidChars) To UBound(invalidChars)

        cleaned = Replace(cleaned, CStr(invalidChars(i)), "_")

    Next i



    cleaned = Replace(cleaned, vbTab, "_")

    Do While InStr(cleaned, "__") > 0

        cleaned = Replace(cleaned, "__", "_")

    Loop



    cleaned = Trim$(cleaned)

    If Len(cleaned) = 0 Then cleaned = "model"

    SanitizeFileStem = cleaned

End Function



Private Function MakeUniqueFileStem(ByVal stem As String, ByVal usedNames As Object) As String

    Dim counter As Long

    Dim candidate As String



    If Not usedNames.Exists(LCase$(stem)) Then

        usedNames.Add LCase$(stem), 1

        MakeUniqueFileStem = stem

        Exit Function

    End If



    counter = CLng(usedNames(LCase$(stem))) + 1

    usedNames(LCase$(stem)) = counter

    candidate = stem & "_" & Format$(counter, "00")



    Do While usedNames.Exists(LCase$(candidate))

        counter = counter + 1

        usedNames(LCase$(stem)) = counter

        candidate = stem & "_" & Format$(counter, "00")

    Loop



    usedNames.Add LCase$(candidate), 1

    MakeUniqueFileStem = candidate

End Function



Private Function EnsureTrailingBackslash(ByVal folderPath As String) As String

    If Right$(folderPath, 1) = "\" Then

        EnsureTrailingBackslash = folderPath

    Else

        EnsureTrailingBackslash = folderPath & "\"

    End If

End Function



Private Sub EnsureFolderExists(ByVal folderPath As String)

    Dim fso As Object



    Set fso = CreateObject("Scripting.FileSystemObject")

    If Not fso.FolderExists(folderPath) Then

        CreateFolderRecursive fso, EnsureTrailingBackslash(folderPath)

    End If

End Sub



Private Sub CreateFolderRecursive(ByVal fso As Object, ByVal folderPath As String)

    Dim parentPath As String

        Dim defaultExportFolder As String
        Dim exportFolder As String
    If fso.FolderExists(folderPath) Then Exit Sub



    parentPath = Left$(folderPath, InStrRev(Left$(folderPath, Len(folderPath) - 1), "\"))

    If Len(parentPath) > 0 And Not fso.FolderExists(parentPath) Then

        CreateFolderRecursive fso, parentPath

    End If



    If Not fso.FolderExists(folderPath) Then fso.CreateFolder folderPath

End Sub



Private Function FileExists(ByVal filePath As String) As Boolean

    FileExists = (Len(Dir$(filePath, vbNormal)) > 0)

End Function



Private Sub ConfigureExcelApp(ByVal excelApp As Object)

    On Error Resume Next

    excelApp.Visible = False

    excelApp.DisplayAlerts = False

    excelApp.ScreenUpdating = False

    excelApp.EnableEvents = False

    excelApp.Calculation = -4135

    Err.Clear

    On Error GoTo 0

End Sub



Private Function IsSimulationSheet(ByVal sheetName As String) As Boolean

    Dim normalized As String



    normalized = LCase$(Trim$(sheetName))

    IsSimulationSheet = _
        (normalized = "meshing_parameters") Or _
        (normalized = "materials") Or _
        (normalized = "step_configuration") Or _
        (normalized = "materials_library") Or _
        (normalized = "instructions")

End Function

