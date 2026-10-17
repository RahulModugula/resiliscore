"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const previous = document.activeElement; const dialog = ref.current; dialog?.showModal(); return () => { dialog?.close(); if (previous instanceof HTMLElement) previous.focus(); }; }, []);
  return <dialog ref={ref} className="modal" aria-labelledby="modal-title" onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}><div className="modal-heading"><h2 id="modal-title">{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={20} /></button></div>{children}</dialog>;
}
