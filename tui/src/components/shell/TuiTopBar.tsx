/** Slice A — Product name + global status chips. Visual Target §3.2 */
import React from "react";
import { Box, Text } from "ink";
import type { TopBarData } from "../../data/visualShellTypes";
import { DIM_TEXT, ACCENT_TEXT, HIGHLIGHT_TEXT } from "../../theme/visualShellTheme";
import { formatStatusChip } from "../../theme/statusTokens";

interface TuiTopBarProps {
  data: TopBarData;
  width: number;
}

export function TuiTopBar({ data, width }: TuiTopBarProps) {
  const statusChips = [
    { label: `Runtime: ${data.mode === "ACT" ? "unified" : data.mode}`, color: "cyan" as const },
    { label: `Mode: ${data.mode}`, color: "cyan" as const },
    { label: `Lens: ${data.lens}`, color: "magenta" as const },
    { label: `Provider: ${data.provider}`, color: "gray" as const },
  ];

  const chips = statusChips
    .map((c) => formatStatusChip(c))
    .join("  ");

  const content = `${data.productName}    ${chips}`;
  const padded = content.padEnd(width - 2).substring(0, width - 2);

  return (
    <Box width={width} height={1}>
      <Text dimColor>{padded}</Text>
    </Box>
  );
}
