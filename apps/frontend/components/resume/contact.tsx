import React from 'react';
import { Mail, Phone, MapPin, Globe, Linkedin, Github, Link as LinkIcon } from 'lucide-react';
import type { Contact, ContactKind, EntryLink } from '@/lib/types/document';
import { cn } from '@/lib/utils';
import baseStyles from './styles/_base.module.css';

type IconComponent = React.ComponentType<{ size?: number }>;

const CONTACT_ICONS: Record<ContactKind, IconComponent> = {
  email: Mail,
  phone: Phone,
  website: Globe,
  github: Github,
  linkedin: Linkedin,
  location: MapPin,
  other: LinkIcon,
};

const LINK_ICONS: Record<EntryLink['kind'], IconComponent> = {
  github: Github,
  website: Globe,
  linkedin: Linkedin,
  other: LinkIcon,
};

/** Absolute URLs are left alone; bare hosts get `https://`. */
function withProtocol(value: string): string {
  if (value.startsWith('//') || /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(value)) return value;
  return `https://${value}`;
}

/** Human-facing form of a URL: no scheme, no `www.`, no trailing slash. */
export function displayUrl(value: string): string {
  return value
    .replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//, '')
    .replace(/^www\./, '')
    .replace(/\/$/, '');
}

/** `contact.url` wins; otherwise the href is derived from `kind` + `value`. */
export function contactHref(contact: Contact): string | undefined {
  const url = contact.url.trim();
  if (url) return withProtocol(url);

  const value = contact.value.trim();
  if (!value) return undefined;

  switch (contact.kind) {
    case 'email':
      return `mailto:${value}`;
    case 'phone':
      return `tel:${value}`;
    case 'website':
    case 'github':
    case 'linkedin':
      return withProtocol(value);
    case 'location':
    case 'other':
      return undefined;
  }
}

interface ContactValueProps {
  contact: Contact;
  showIcon?: boolean;
  iconSize?: number;
  /** Wrapper classes — templates use this for chips/pills. */
  className?: string;
  /** Classes for the icon wrapper — templates use this for icon circles. */
  iconClassName?: string;
}

/**
 * One header contact. `label` is the displayed text; when it is empty the
 * contact renders icon-only (per the document contract), falling back to the
 * value when no icon is being shown so a contact is never rendered blank.
 */
export const ContactValue: React.FC<ContactValueProps> = ({
  contact,
  showIcon = false,
  iconSize = 12,
  className,
  iconClassName,
}) => {
  const Icon = CONTACT_ICONS[contact.kind];
  const text = contact.label.trim() || (showIcon ? '' : displayUrl(contact.value.trim()));
  if (!text && !showIcon) return null;

  const href = contactHref(contact);

  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      {showIcon && (
        <span className={cn('inline-flex items-center', iconClassName)}>
          <Icon size={iconSize} />
        </span>
      )}
      {text &&
        (href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(baseStyles['resume-link'], 'hover:underline')}
          >
            {text}
          </a>
        ) : (
          <span>{text}</span>
        ))}
    </span>
  );
};

/** An entry's link, rendered as a compact pill with the matching glyph. */
export const EntryLinkPill: React.FC<{ link: EntryLink; iconSize?: number }> = ({
  link,
  iconSize = 10,
}) => {
  const url = link.url.trim();
  if (!url) return null;

  const Icon = LINK_ICONS[link.kind];

  return (
    <a
      href={withProtocol(url)}
      target="_blank"
      rel="noopener noreferrer"
      className={baseStyles['resume-link-pill']}
    >
      <Icon size={iconSize} />
      {displayUrl(url)}
    </a>
  );
};
