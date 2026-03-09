import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

interface WorkerUnavailableStateProps {
  title?: string;
  message?: string;
}

export default function WorkerUnavailableState({
  title = "Worker indisponível",
  message = "O dashboard depende do worker interno. Verifique o processo em :8081 ou a rota `/api/worker` no web server.",
}: WorkerUnavailableStateProps) {
  return (
    <Alert className="border-red-500/30 bg-red-500/5 text-red-100">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
