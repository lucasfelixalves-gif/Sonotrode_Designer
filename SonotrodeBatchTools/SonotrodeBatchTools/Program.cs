using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using ClosedXML.Excel;
using TopSolid.Kernel.Automating;
using TopSolid.Cad.Design.Automating;

namespace SonotrodeBatchApp
{
    static class Program
    {
        private const double MM_TO_METERS = 1000.0;
        private const string OUTPUT_FOLDER_NAME = "02_Geometry_STEP";
        private const string GEOMETRY_SHEET_NAME = "Geometry";
        private const string MODEL_NAME_COLUMN = "Model_name";

        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            try
            {
                // Conecta silenciosamente ao TopSolid que já está aberto no computador
                TopSolidHost.Connect();

                if (!TopSolidHost.IsConnected)
                {
                    MessageBox.Show("TopSolid não está aberto. Abra o TopSolid e o modelo 3D primeiro.", "Erro", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }

                ExecuteBatchRun();
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Erro de conexão:\n{ex.Message}", "Erro Crítico", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally
            {
                if (TopSolidHost.IsConnected)
                {
                    TopSolidHost.Disconnect();
                }
            }
        }

        private static void ExecuteBatchRun()
        {
            DocumentId docId = TopSolidHost.Documents.EditedDocument;
            if (docId.Equals(default(DocumentId)))
            {
                MessageBox.Show("Nenhum documento CAD ativo encontrado.", "Erro", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            string projectRootPath;
            using (FolderBrowserDialog folderDialog = new FolderBrowserDialog())
            {
                folderDialog.Description = "Selecione a pasta 'Project Root'";
                folderDialog.ShowNewFolderButton = false;

                if (folderDialog.ShowDialog() != DialogResult.OK)
                {
                    return; // Usuário cancelou a seleção
                }
                projectRootPath = folderDialog.SelectedPath;
            }

            string excelPath = Path.Combine(projectRootPath, "01_Master_Config", "Master_Config.xlsx");
            
            if (!File.Exists(excelPath))
            {
                MessageBox.Show("Configuration file not found. Run the Python 'Create Master Workbook' tool first.", "Erro", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            string outputFolder = Path.Combine(projectRootPath, OUTPUT_FOLDER_NAME);
            
            try
            {
                if (!Directory.Exists(outputFolder))
                {
                    Directory.CreateDirectory(outputFolder);
                }

                // Temporary mockup of ProcessExcelAndExportModels
                // ProcessExcelAndExportModels(docId, excelPath, outputFolder);
                MessageBox.Show($"Root selecionado: {projectRootPath}\nExcel encontrado: {excelPath}\nPronto para processar!", "Sucesso", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch (Exception ex) when (ex is DirectoryNotFoundException || ex is IOException || ex is UnauthorizedAccessException)
            {
                MessageBox.Show($"Erro de acesso ou leitura no sistema de arquivos:\n{ex.Message}", "Erro", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private static bool UpdateTopSolidParameters(DocumentId docId, IXLRow row, Dictionary<int, string> columnHeaderMap)
        {
            bool anyUpdated = false;

            // Inicia um bloco de modificação para agrupar as alterações e garantir a regeneração ao final
            TopSolidHost.Application.StartModification("Atualização de parâmetros via SonotrodeBatch", false);

            try
            {
                foreach (var mapping in columnHeaderMap)
                {
                    int colIndex = mapping.Key;
                    string paramName = mapping.Value;

                    // Ignora a coluna de nome do modelo
                    if (paramName.Equals(MODEL_NAME_COLUMN, StringComparison.OrdinalIgnoreCase))
                        continue;

                    IXLCell cell = row.Cell(colIndex);
                    if (cell.IsEmpty())
                        continue;

                    // Tenta converter o valor da célula para double (em milímetros)
                    if (cell.TryGetValue(out double valueInMm))
                    {
                        // O TopSolid trabalha com metros internamente
                        double valueInMeters = valueInMm / MM_TO_METERS;

                        try
                        {
                            // Busca o ElementId do parâmetro pelo nome de string no documento
                            ElementId paramId = TopSolidHost.Elements.SearchByName(docId, paramName);

                            if (!paramId.IsEmpty)
                            {
                                // Aplica o valor em metros ao parâmetro CAD
                                TopSolidHost.Parameters.SetRealValue(paramId, valueInMeters);
                                anyUpdated = true;
                            }
                        }
                        catch (Exception)
                        {
                            // Ignora cabeçalhos que não têm um parâmetro correspondente no CAD
                            continue;
                        }
                    }
                }
            }
            finally
            {
                // Finaliza o bloco de modificação permitindo regeneração automática do documento
                TopSolidHost.Application.EndModification(true, true);
            }

            return anyUpdated;
        }
    }
}
