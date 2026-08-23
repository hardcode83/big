---
name: AutoHostAI Cyber-SaaS
colors:
  surface: '#0f131c'
  surface-dim: '#0f131c'
  surface-bright: '#353943'
  surface-container-lowest: '#0a0e17'
  surface-container-low: '#181b25'
  surface-container: '#1c2029'
  surface-container-high: '#262a34'
  surface-container-highest: '#31353f'
  on-surface: '#dfe2ef'
  on-surface-variant: '#bcc9c5'
  inverse-surface: '#dfe2ef'
  inverse-on-surface: '#2c303a'
  outline: '#879390'
  outline-variant: '#3d4946'
  surface-tint: '#70d8c8'
  primary: '#70d8c8'
  on-primary: '#003731'
  primary-container: '#32a192'
  on-primary-container: '#00302a'
  inverse-primary: '#006b5f'
  secondary: '#bcc7de'
  on-secondary: '#263143'
  secondary-container: '#3e495d'
  on-secondary-container: '#aeb9d0'
  tertiary: '#00daf3'
  on-tertiary: '#00363d'
  tertiary-container: '#009fb2'
  on-tertiary-container: '#002f35'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#8df5e4'
  primary-fixed-dim: '#70d8c8'
  on-primary-fixed: '#00201c'
  on-primary-fixed-variant: '#005048'
  secondary-fixed: '#d8e3fb'
  secondary-fixed-dim: '#bcc7de'
  on-secondary-fixed: '#111c2d'
  on-secondary-fixed-variant: '#3c475a'
  tertiary-fixed: '#9cf0ff'
  tertiary-fixed-dim: '#00daf3'
  on-tertiary-fixed: '#001f24'
  on-tertiary-fixed-variant: '#004f58'
  background: '#0f131c'
  on-background: '#dfe2ef'
  surface-variant: '#31353f'
  surface-elevated: '#131D31'
  surface-highlight: '#1E293B'
  text-primary: '#F8FAFC'
  text-secondary: '#94A3B8'
  text-muted: '#64748B'
  state-success: '#10B981'
  state-warning: '#F59E0B'
  state-error: '#EF4444'
  state-info: '#38BDF8'
typography:
  display-2xl:
    fontFamily: Inter
    fontSize: 56px
    fontWeight: '800'
    lineHeight: 64px
    letterSpacing: -0.03em
  display-xl:
    fontFamily: Inter
    fontSize: 44px
    fontWeight: '800'
    lineHeight: 52px
    letterSpacing: -0.025em
  display-lg-mobile:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '800'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.015em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: -0.005em
  body-medium:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: '0'
  body-base:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: '0'
  data-mono:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: -0.01em
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.06em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 32px
  3xl: 48px
  4xl: 64px
  gutter: 16px
  margin-mobile: 16px
  margin-desktop: 32px
---

## Brand & Style
The brand personality is high-precision, automated, and professional, targeting property managers who require "instrumentation-grade" reliability. The visual style is a sophisticated blend of **Modern Corporate** and **Glassmorphism**, set against a deep technical backdrop. 

Key attributes include:
- **Technical Sophistication**: Utilizing glows and blurs to imply a futuristic, "AI-driven" engine under the hood.
- **Precision**: Clean lines and high-contrast primary accents against dark surfaces to ensure data readability.
- **Dynamic Energy**: Subtle linear gradients and hover transitions that make the interface feel alive and responsive.

## Colors
The palette is built on a "Midnight Technical" foundation.
- **Primary**: A signature Teal (#00897b) used for brand identity, primary actions, and critical data highlights. It features an associated glow effect.
- **Backgrounds**: A hierarchy of dark blues and grays (from #0a0e17 to #353943) creates depth without sacrificing the "dark mode" comfort.
- **Functional Accents**: Standardized semantic colors for status tracking (Success/Emerald, Warning/Amber, Error/Red, Info/Sky).
- **Text**: High-contrast Slate-50 (#F8FAFC) for primary reading and Slate-400 (#94A3B8) for supporting metadata.

## Typography
The system uses a dual-font approach to balance readability with technical aesthetics.
- **Primary Interface (Inter)**: Used for all UI controls and long-form text. Display weights are set to Extra Bold (800) with tight tracking to create a strong, modern editorial feel.
- **Data & Metrics (JetBrains Mono)**: Used specifically for numerical data, statistics, and system status to evoke a "dashboard" or "code" aesthetic.
- **Hierarchy**: Clear distinction is made between "Display" (marketing/impact) and "Headline" (structural) roles.

## Layout & Spacing
The system follows a **Fixed Grid** approach for web, centering content within a 1280px (7xl) container. 
- **Rhythm**: A 4px baseline unit drives all padding and margins. 
- **Desktop**: 32px side margins with 24px-32px gutters between cards.
- **Mobile**: 16px side margins with a single-column reflow for cards and stats.
- **Sections**: Vertical breathing room is generous, utilizing 64px to 96px (4xl+) to separate major narrative blocks.

## Elevation & Depth
Depth is created through light and transparency rather than traditional physical shadows.
- **Tonal Layering**: Backgrounds use `#0f131c`. Cards use a slightly lighter `#181b25`.
- **Glassmorphism**: The navigation bar and stat cards use `backdrop-blur (12px)` with semi-transparent backgrounds (`80%` or `60%` opacity) to create a sense of stacked glass.
- **Glows**: Primary buttons and headings feature "Ambient Glows" — soft, diffused drop shadows tinted with the primary Teal color (`rgba(0, 137, 123, 0.2)`).
- **Outlines**: Borders are strictly defined at 1px using `#262a34` (surface-container-high) to maintain a crisp, technical edge.

## Shapes
The shape language is refined and disciplined. 
- **Base Components**: Buttons and small inputs use a subtle 4px (base) radius.
- **Containers**: Feature cards and Stat cards use a more pronounced 12px (xl) radius.
- **Icons**: Enclosed within 8px (lg) rounded boxes for a consistent "app icon" appearance within the layout.

## Components
- **Primary Buttons**: Solid Teal (#00897b) with white text. Must include a transition on hover that increases the shadow spread and slightly shifts the Y-position (-1px).
- **Secondary Buttons**: Transparent with a 1px border (#1E293B). Hover state introduces a subtle Teal tint (`rgba(0, 137, 123, 0.1)`) and border color change.
- **Feature Cards**: Interactive containers with a hidden top-border gradient that fades in on hover. Background: `#181b25`, Border: `#262a34`.
- **Stat Cards**: Glassmorphic containers. Use `JetBrains Mono` for the primary metric and `Inter` for the descriptor.
- **Navigation**: Sticky, blurred background with a bottom border highlight. Links should have a subtle scale-down (95%) effect on active click.
- **Icons**: Utilize Material Symbols Outlined, maintaining a weight that matches the surrounding typography (Standard or Medium).