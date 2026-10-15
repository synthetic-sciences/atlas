import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Dialog } from "@base-ui/react/dialog";
import { Field } from "@base-ui/react/field";
import { Select } from "@base-ui/react/select";
import { Tabs } from "@base-ui/react/tabs";

export { Dialog as BaseDialog, Field as BaseField, Select as BaseSelect, Tabs as BaseTabs };

type TabItem<T extends string> = {
  value: T;
  label: ReactNode;
  meta?: ReactNode;
};

export function SegmentTabs<T extends string>({
  value,
  items,
  ariaLabel,
  onValueChange,
}: {
  value: T;
  items: TabItem<T>[];
  ariaLabel: string;
  onValueChange: (value: T) => void;
}) {
  return (
    <Tabs.Root
      className="base-tabs"
      value={value}
      onValueChange={(next) => onValueChange(String(next) as T)}
    >
      <Tabs.List className="base-tabs-list" aria-label={ariaLabel}>
        {items.map((item) => (
          <Tabs.Tab key={item.value} className="base-tabs-tab" value={item.value}>
            <span>{item.label}</span>
            {item.meta ? <span className="base-tabs-meta">{item.meta}</span> : null}
          </Tabs.Tab>
        ))}
        <Tabs.Indicator className="base-tabs-indicator" />
      </Tabs.List>
    </Tabs.Root>
  );
}

type SelectItem<T extends string> = {
  value: T;
  label: ReactNode;
};

export function SelectField<T extends string>({
  value,
  items,
  label,
  ariaLabel,
  onValueChange,
  width,
}: {
  value: T;
  items: SelectItem<T>[];
  label?: ReactNode;
  ariaLabel?: string;
  onValueChange: (value: T) => void;
  width?: number | string;
}) {
  return (
    <div className="base-select-field" style={width ? { width } : undefined}>
      <Select.Root
        value={value}
        items={items}
        onValueChange={(next) => {
          if (next != null) onValueChange(String(next) as T);
        }}
      >
        {label ? <Select.Label className="base-select-label">{label}</Select.Label> : null}
        <Select.Trigger className="base-select-trigger" aria-label={ariaLabel}>
          <Select.Value className="base-select-value" />
          <Select.Icon className="base-select-icon">
            <ChevronDown size={13} strokeWidth={1.7} />
          </Select.Icon>
        </Select.Trigger>
        <Select.Portal>
          <Select.Positioner sideOffset={6} className="base-select-positioner">
            <Select.Popup className="base-select-popup">
              <Select.List className="base-select-list">
                {items.map((item) => (
                  <Select.Item
                    key={item.value}
                    value={item.value}
                    className="base-select-item"
                  >
                    <Select.ItemText>{item.label}</Select.ItemText>
                  </Select.Item>
                ))}
              </Select.List>
            </Select.Popup>
          </Select.Positioner>
        </Select.Portal>
      </Select.Root>
    </div>
  );
}
