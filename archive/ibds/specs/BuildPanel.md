## BuildPanel Component Specification

### 1. TypeScript Interfaces & Imports

```typescript
import { useState, useEffect } from 'react';
import { Badge, Button, ScrollArea, Tabs, Text, Box, Flex, Center, Skeleton, rem } from '@mantine/core';
import { IconFile, IconFolder, IconCode, IconRefresh, IconExternalLink } from '@tabler/icons-react';

type ProjectType = 'website' | 'content';
type FilterType = 'all' | 'website' | 'content';
type TabType = 'files' | 'folder';

interface Project {
  id: string;
  name: string;
  type: ProjectType;
  fileCount: number;
  size: string;
  modified: string;
  status: 'idle' | 'building' | 'deployed' | 'failed';
}

interface FileNode {
  name: string;
  type: 'file' | 'folder';
  extension?: string;
  children?: FileNode[];
  content?: string;
}

interface FolderEntry {
  name: string;
  type: 'file' | 'folder';
  path: string;
}

interface BuildPanelProps {
  className?: string;
}

interface BuildPanelState {
  projects: Project[];
  selectedProject: Project | null;
  filter: FilterType;
  activeTab: TabType;
  fileTree: FileNode[];
  folderEntries: FolderEntry[];
  currentPath: string;
  loadingProjects: boolean;
  loadingDetails: boolean;
  error: string | null;
  lastFetch: Date | null;
}
```

### 2. Component Structure & Layout

```typescript
// Layout hierarchy:
// Box (padding: 12px)
//  ├── Flex (h: 36px, align: center) Header
//  │   ├── Text "BUILD" (fw: 500, size: sm)
//  │   ├── Badge project count
//  │   └── SegmentedControl (filter buttons)
//  └── Flex (flex: 1, gap: md) Content
//      ├── Box (w: 40%) Left Column
//      │   └── ScrollArea project list
//      │       └── Stack (gap: xs) project rows
//      │           ├── Flex (justify: space-between) per row
//      │           │   ├── Flex (gap: xs) meta
//      │           │   └── Button Deploy
//      └── Box (w: 60%) Right Column
//          └── Conditional: Project details
//              ├── Flex header
//              ├── Tabs (files/folder)
//              ├── ScrollArea content
//              └── Action buttons

// Component sections:
// - HeaderBar: label, count badge, filter controls
// - ProjectList: scrollable list with row selection
// - ProjectDetails: conditional render on selection
// - FileTree: collapsible tree with icons
// - CodePreview: max 30 lines, monospace font
// - FolderView: breadcrumb navigation
```

### 3. Data Fetching Strategy

```typescript
// Endpoints:
// GET /webgen/sites → returns Project[]
// GET /content/jobs → returns Project[]
// GET /projects/{id}/files → returns FileNode[]
// GET /projects/{id}/folder?path={path} → returns FolderEntry[]
// POST /folders/analyze → { path: string }
// POST /projects/{id}/build → {} triggers build

// Polling: 5s interval via useEffect
// - Merge webgen + content arrays
// - Update selectedProject if exists in new data
// - Maintain selection state across polls

// Loading states:
// - Initial project fetch: show skeleton rows (5)
// - Project selection: show detail skeleton
// - File/folder fetch: show tab skeleton

// Error handling:
// - Projects fetch fail: show error banner
// - Details fetch fail: show error message in right column
// - Build request fail: show notification
```

### 4. Edge Cases to Handle

```typescript
// - Empty project list: show "No projects" message
// - Type filtering: maintain selection if filtered out
// - Active build status: disable build button, show spinner
// - Large file trees: virtualize if >1000 nodes
// - Long file content: truncate at 30 lines with ellipsis
// - Path traversal: prevent ../ navigation
// - Rapid selection changes: cancel previous requests
// - Network offline: show connection status indicator
// - Date parsing: handle invalid modified dates
// - File extension mapping: fallback to generic icon
// - Folder navigation: maintain scroll position
```

### 5. What BuildPanel Must NOT Do

```typescript
// - Must NOT handle authentication
// - Must NOT implement routing/navigation
// - Must NOT manage global state
// - Must NOT implement drag-and-drop
// - Must NOT handle file uploads
// - Must NOT implement search/filter beyond type
// - Must NOT cache data beyond component lifecycle
// - Must NOT implement build logs viewing
// - Must NOT handle deployment beyond button click
// - Must NOT modify project data
// - Must NOT implement settings/configuration
// - Must NOT handle file editing
```