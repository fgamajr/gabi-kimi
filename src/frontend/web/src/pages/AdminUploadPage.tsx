import { useCallback, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FileUp, FileCode, Loader2, ClipboardPaste, ListTodo } from "lucide-react";
import { toast } from "sonner";
import { uploadAdminFile } from "@/lib/uploadApi";
import { parseXmlPreview, type XmlPreview } from "@/lib/xmlPreview";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const MAX_ZIP_BYTES = 200 * 1024 * 1024;
const ACCEPT = ".xml,.zip";
const ACCEPT_MIME = "application/xml,text/xml,application/zip";

export default function AdminUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<XmlPreview | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [pasteXml, setPasteXml] = useState("");
  const [pasteUploading, setPasteUploading] = useState(false);
  const [pasteProgress, setPasteProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleFileSelect = useCallback((selected: File | null) => {
    setFile(selected);
    setPreview(null);
    if (!selected) return;
    const isXml =
      selected.name.toLowerCase().endsWith(".xml") ||
      selected.type === "application/xml" ||
      selected.type === "text/xml";
    if (isXml) {
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const text = String(reader.result);
          setPreview(parseXmlPreview(text));
        } catch {
          setPreview({ articleCount: 0, dateMin: null, dateMax: null, sections: [], error: "Erro ao ler arquivo" });
        }
      };
      reader.readAsText(selected, "utf-8");
    }
  }, []);

  const validateFile = (f: File): string | null => {
    const isZip = f.name.toLowerCase().endsWith(".zip") || f.type === "application/zip";
    const isXml =
      f.name.toLowerCase().endsWith(".xml") || f.type === "application/xml" || f.type === "text/xml";
    if (!isZip && !isXml) return "Aceito apenas arquivos .xml ou .zip";
    if (f.size > MAX_ZIP_BYTES) return "Tamanho máximo: 200 MB";
    return null;
  };

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (!f) return;
      const err = validateFile(f);
      if (err) {
        toast.error(err);
        return;
      }
      handleFileSelect(f);
    },
    [handleFileSelect]
  );

  const onFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    if (f) {
      const err = validateFile(f);
      if (err) {
        toast.error(err);
        e.target.value = "";
        return;
      }
    }
    handleFileSelect(f);
    e.target.value = "";
  };

  const openFilePicker = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const startUpload = async () => {
    if (!file) return;
    setUploading(true);
    setProgress(0);
    try {
      const result = await uploadAdminFile(file, (p) => setProgress(p));
      toast.success(`Job criado: ${result.job_id}`);
      setFile(null);
      setPreview(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha no upload");
    } finally {
      setUploading(false);
      setProgress(0);
    }
  };

  const startPasteUpload = async () => {
    const xml = pasteXml.trim();
    if (!xml) {
      toast.error("Cole o conteúdo XML");
      return;
    }
    setPasteUploading(true);
    setPasteProgress(0);
    try {
      const blob = new Blob([xml], { type: "application/xml" });
      const f = new File([blob], "pasted.xml", { type: "application/xml" });
      const result = await uploadAdminFile(f, (p) => setPasteProgress(p));
      toast.success(`Job criado: ${result.job_id}`);
      setPasteXml("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha no upload");
    } finally {
      setPasteUploading(false);
      setPasteProgress(0);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-2xl px-4 py-8">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold text-foreground mb-2">Upload DOU</h1>
            <p className="text-sm text-muted-foreground">
              Envie um arquivo XML ou ZIP (até 200 MB). O processamento é feito em segundo plano.
            </p>
          </div>
          <Button asChild variant="ghost" size="sm" className="w-fit text-muted-foreground">
            <Link to="/admin/jobs" className="inline-flex items-center gap-2">
              <ListTodo className="w-4 h-4" /> Ver jobs
            </Link>
          </Button>
        </div>

        <Tabs defaultValue="file" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="file" className="gap-2">
              <FileUp className="w-4 h-4" /> Arquivo
            </TabsTrigger>
            <TabsTrigger value="paste" className="gap-2">
              <ClipboardPaste className="w-4 h-4" /> Colar XML
            </TabsTrigger>
          </TabsList>

          <TabsContent value="file" className="mt-6 space-y-4">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className={cn(
                "border-2 border-dashed rounded-xl p-8 text-center transition-colors",
                dragOver ? "border-primary bg-primary/5" : "border-muted-foreground/25 bg-muted/30"
              )}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPT}
                className="hidden"
                id="admin-upload-file"
                onChange={onFileInputChange}
              />
              <div aria-describedby="admin-upload-help">
                <FileCode className="w-12 h-12 mx-auto text-muted-foreground mb-3" />
                <p className="text-sm font-medium text-foreground">
                  Arraste um arquivo aqui ou escolha no dispositivo
                </p>
                <p id="admin-upload-help" className="text-xs text-muted-foreground mt-1">.xml ou .zip, até 200 MB</p>
                <Button
                  type="button"
                  variant="secondary"
                  className="mt-4 min-h-[44px]"
                  onClick={openFilePicker}
                >
                  Escolher arquivo
                </Button>
              </div>
            </div>

            {file && (
              <div className="rounded-lg border border-border bg-card p-4 space-y-3">
                <p className="text-sm font-medium text-foreground">{file.name}</p>
                <p className="text-xs text-muted-foreground">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
                {preview && (
                  <div className="text-sm text-muted-foreground space-y-1">
                    {preview.error && (
                      <p className="text-amber-600 dark:text-amber-400">{preview.error}</p>
                    )}
                    {preview.articleCount > 0 && (
                      <p>Artigos detectados: {preview.articleCount}</p>
                    )}
                    {(preview.dateMin || preview.dateMax) && (
                      <p>
                        Período: {preview.dateMin ?? "—"} a {preview.dateMax ?? "—"}
                      </p>
                    )}
                    {preview.sections.length > 0 && (
                      <p>Seções: {preview.sections.slice(0, 5).join(", ")}{preview.sections.length > 5 ? "…" : ""}</p>
                    )}
                  </div>
                )}
                {uploading && (
                  <div className="space-y-2" aria-live="polite">
                    <Progress value={progress} className="h-2" />
                    <p className="text-xs text-muted-foreground flex items-center gap-1">
                      <Loader2 className="w-3 h-3 animate-spin" /> Enviando… {progress}%
                    </p>
                  </div>
                )}
                <Button
                  onClick={startUpload}
                  disabled={uploading}
                  className="w-full sm:w-auto"
                >
                  {uploading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Enviando…
                    </>
                  ) : (
                    "Enviar"
                  )}
                </Button>
              </div>
            )}
          </TabsContent>

          <TabsContent value="paste" className="mt-6 space-y-4">
            <Textarea
              placeholder="Cole o conteúdo XML aqui…"
              value={pasteXml}
              onChange={(e) => setPasteXml(e.target.value)}
              className="min-h-[200px] font-mono text-sm"
              disabled={pasteUploading}
            />
            {pasteUploading && (
              <div className="space-y-2" aria-live="polite">
                <Progress value={pasteProgress} className="h-2" />
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <Loader2 className="w-3 h-3 animate-spin" /> Enviando… {pasteProgress}%
                </p>
              </div>
            )}
            <Button
              onClick={startPasteUpload}
              disabled={!pasteXml.trim() || pasteUploading}
              className="w-full sm:w-auto"
            >
              {pasteUploading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Enviando…
                </>
              ) : (
                "Enviar XML colado"
              )}
            </Button>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
