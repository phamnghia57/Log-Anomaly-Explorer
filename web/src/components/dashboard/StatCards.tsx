import type { ClusterRecord } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { AlertTriangle, CircleCheck, Layers, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

export function StatCards({ clusters }: { clusters: ClusterRecord[] }) {
  const total = clusters.length;
  const alerted = clusters.filter((c) => c.status === "alerted").length;
  const anomalous = clusters.filter((c) => c.status === "anomalous").length;
  const maxScore = clusters.reduce((m, c) => Math.max(m, c.score), 0);

  const items = [
    { label: "Tổng số cụm", value: total, icon: Layers, tone: "text-foreground" },
    { label: "Alerted", value: alerted, icon: AlertTriangle, tone: "text-red-600 dark:text-red-400" },
    { label: "Anomalous", value: anomalous, icon: TrendingUp, tone: "text-amber-600 dark:text-amber-400" },
    {
      label: "Score cao nhất",
      value: maxScore.toFixed(2),
      icon: CircleCheck,
      tone: "text-foreground",
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label} className="py-4">
          <CardContent className="flex items-center justify-between px-4">
            <div>
              <p className="text-xs text-muted-foreground">{item.label}</p>
              <p className="text-2xl font-semibold tabular-nums">{item.value}</p>
            </div>
            <item.icon className={cn("h-8 w-8 opacity-70", item.tone)} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
