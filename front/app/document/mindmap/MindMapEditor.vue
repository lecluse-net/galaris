<template>
  <Teleport to="body" :disabled="!standaloneFullscreen">
  <q-banner v-if="!map || !root" dense class="text-negative" role="alert">{{ t('documents.mindmap.invalid') }}</q-banner>
  <section v-else class="mindmap" :class="{ 'mindmap--dark': $q.dark.isActive, 'editorial-fullscreen': standaloneFullscreen }"
    :style="mapThemeStyle" :aria-label="t('documents.formats.mindmap')"
    @focusin="onMapFocus" @focusout="onMapFocus" @keydown.esc.capture="onCutEscape" @keydown.esc="onFullscreenEscape">
    <div ref="toolbar" class="editorial-toolbars" @keydown.esc="onBodyEscape">
      <DocumentToolbarFrame v-show="!activeBody" ref="mapToolbar" mode="simple" class="mindmap-tools" :label="t('documents.formats.mindmap')" :document-navigation="!embedded">
      <div class="editorial-toolbar-group" role="group" :aria-label="t('documents.mindmap.view')">
        <span class="editorial-toolbar-title">{{ t('documents.mindmap.view') }}</span>
        <div class="editorial-toolbar-row">
        <q-btn flat dense icon="zoom_out" :aria-label="t('documents.mindmap.zoomOut')" @click="zoomStep(-1)" />
        <q-btn flat dense icon="zoom_in" :aria-label="t('documents.mindmap.zoomIn')" @click="zoomStep(1)" />
        <q-btn dense outline :label="`${percentage}%`" :aria-label="t('documents.mindmap.resetZoom')" @click="reset" />
        <q-btn flat dense :icon="editorialIcon('layout.full', 'fit_screen')" :aria-label="t('documents.mindmap.fit')" @click="fit">
          <q-tooltip>{{ t('documents.mindmap.fit') }}</q-tooltip>
        </q-btn>
        <q-btn flat dense :icon="fullscreen ? editorialIcon('restore', 'fullscreen_exit') : editorialIcon('fullscreen', 'fullscreen')"
          :aria-label="fullscreenLabel" :aria-pressed="fullscreen" :color="fullscreen ? 'primary' : undefined" @click="toggleFullscreen">
          <q-tooltip v-if="!fullscreen">{{ fullscreenLabel }}</q-tooltip>
        </q-btn>
        <q-btn flat dense :icon="editorialIcon('help', 'keyboard')" :aria-label="t('richEditor.help')" @click="helpOpen = true">
          <q-tooltip>{{ t('richEditor.help') }} (Alt+0)</q-tooltip>
        </q-btn>
        </div>
      </div>
      <div class="editorial-toolbar-group" role="group" :aria-label="t('richEditor.groups.editing')">
        <span class="editorial-toolbar-title">{{ t('richEditor.groups.editing') }}</span>
        <div class="editorial-toolbar-row">
          <q-btn v-if="!readonly" flat dense :icon="editorialIcon('undo', 'undo')" :aria-label="t('richEditor.undo')"
            :disable="!undo.length && !cutPending" @click="restoreHistory('undo')"><q-tooltip>{{ t('richEditor.undo') }}</q-tooltip></q-btn>
          <q-btn v-if="!readonly" flat dense :icon="editorialIcon('redo', 'redo')" :aria-label="t('richEditor.redo')"
            :disable="!redo.length" @click="restoreHistory('redo')"><q-tooltip>{{ t('richEditor.redo') }}</q-tooltip></q-btn>
          <q-btn flat dense :icon="editorialIcon('find', 'search')" :aria-label="t('richEditor.find')" :aria-expanded="searchOpen"
            @click="searchOpen ? closeSearch() : openSearch()"><q-tooltip>{{ t('richEditor.find') }}</q-tooltip></q-btn>
          <q-btn flat dense :icon="editorialIcon('selectAll', 'select_all')" :aria-label="t('richEditor.selectAll')"
            @click="selectAllBranches"><q-tooltip>{{ t('richEditor.selectAll') }}</q-tooltip></q-btn>
          <template v-if="!readonly">
            <q-btn flat dense icon="content_cut" :disable="!canMoveSelection" :aria-label="t('richEditor.clipboard.cut')" @click="storeBranches('cut')">
              <q-tooltip>{{ t('richEditor.clipboard.cut') }}</q-tooltip>
            </q-btn>
            <q-btn v-if="cutPending" flat dense color="primary" icon="cancel" :aria-label="t('documents.mindmapClipboard.cancelCut')"
              @click="cancelCutFromToolbar">
              <q-tooltip>{{ t('documents.mindmapClipboard.cancelCut') }} ({{ t('documents.mindmapHelp.escape') }})</q-tooltip>
            </q-btn>
            <q-btn flat dense :icon="editorialIcon('copy', 'content_copy')" :disable="!selection.length" :aria-label="t('richEditor.clipboard.copy')" @click="storeBranches('copy')">
              <q-tooltip>{{ t('richEditor.clipboard.copy') }}</q-tooltip>
            </q-btn>
            <q-btn flat dense icon="content_paste" :disable="!canAdd(active) && !canPasteBranches(active)" :aria-label="t('richEditor.clipboard.paste')" @click="pasteFromToolbar">
              <q-tooltip>{{ t('richEditor.clipboard.paste') }}</q-tooltip>
            </q-btn>
          </template>
          <q-btn flat dense color="primary" icon="copy_all" :disable="!selectedValues.length"
            :aria-label="t('documents.mindmapValue.copySelected')" @click="copySelectedValues(false)">
            <q-tooltip>{{ t('documents.mindmapValue.copySelected') }}</q-tooltip>
          </q-btn>
          <q-btn flat dense color="primary" icon="table_view" :disable="!selectedValues.length"
            :aria-label="t('documents.mindmapValue.copyTable')" @click="copySelectedValues(true)">
            <q-tooltip>{{ t('documents.mindmapValue.copyTable') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="!readonly || connectorsByNode.has(active.id)" flat dense color="primary" icon="hub"
            :aria-label="t('documents.mindmapConnectors.title')" @click="openSelectedConnectors">
            <q-tooltip>{{ t('documents.mindmapConnectors.title') }}</q-tooltip>
          </q-btn>
        </div>
      </div>
      <div v-if="!readonly" class="editorial-toolbar-group" role="group" :aria-label="t('documents.mindmapThemes.appearance')">
        <span class="editorial-toolbar-title">{{ t('documents.mindmapThemes.appearance') }}</span>
        <div class="editorial-toolbar-row">
          <q-btn flat dense :icon="editorialIcon('tableStyles', 'palette')" :aria-label="t('documents.mindmapThemes.title')" @click="openThemes">
            <q-tooltip>{{ t('documents.mindmapThemes.title') }}</q-tooltip>
          </q-btn>
          <q-btn flat dense :icon="editorialIcon('backgroundColor', 'format_color_fill')" :aria-label="t('richEditor.backgroundColor')" @click="openBackground">
            <q-tooltip>{{ t('richEditor.backgroundColor') }}</q-tooltip>
          </q-btn>
        </div>
      </div>
      <div v-if="!readonly || hasBranches" class="editorial-toolbar-group" role="group" :aria-label="t('documents.mindmap.branches')">
        <span class="editorial-toolbar-title">{{ t('documents.mindmap.branches') }}</span>
        <div class="editorial-toolbar-row">
        <q-btn v-if="!readonly" flat dense icon="add" :disable="!canAdd(active)"
          :aria-label="t('documents.mindmap.addChild')" @click="addBranch(active)">
          <q-tooltip>{{ t('documents.mindmap.addChild') }} (Tab / Insert)</q-tooltip>
        </q-btn>
        <template v-if="!readonly">
          <q-btn flat dense icon="playlist_add" :disable="active.parent === null || !canAdd(byId.get(active.parent))"
            :aria-label="t('documents.mindmap.addSibling')" @click="addSibling">
            <q-tooltip>{{ t('documents.mindmap.addSibling') }}</q-tooltip>
          </q-btn>
          <q-btn flat dense icon="drive_file_move" :disable="!parents.length" :aria-label="t('documents.mindmap.changeParent')"
            @click="changingParent = active.id">
            <q-tooltip>{{ t('documents.mindmap.changeParent') }}</q-tooltip>
          </q-btn>
          <q-btn flat dense :icon="editorialIcon('insertBefore', 'arrow_upward')" :disable="!reorderNeighbor(-1)" :aria-label="t('documents.mindmap.earlier')" @click="reorder(-1)">
            <q-tooltip>{{ t('documents.mindmap.earlier') }}</q-tooltip>
          </q-btn>
          <q-btn flat dense :icon="editorialIcon('insertAfter', 'arrow_downward')" :disable="!reorderNeighbor(1)"
            :aria-label="t('documents.mindmap.later')" @click="reorder(1)">
            <q-tooltip>{{ t('documents.mindmap.later') }}</q-tooltip>
          </q-btn>
          <q-btn flat dense :icon="editorialIcon('remove', 'delete')" color="negative" :disable="!canMoveSelection"
            :aria-label="removeLabel" @click="confirmRemove()">
            <q-tooltip>{{ removeLabel }}</q-tooltip>
          </q-btn>
        </template>
        <q-btn v-if="hasBranches" flat dense icon="unfold_less" :aria-label="t('documents.mindmap.collapseAll')" @click="collapseAll">
          <q-tooltip>{{ t('documents.mindmap.collapseAll') }}</q-tooltip>
        </q-btn>
        <q-btn v-if="hasBranches" flat dense icon="unfold_more" :aria-label="t('documents.mindmap.expandAll')"
          :disable="folded.size === 0" @click="folded.clear()">
          <q-tooltip>{{ t('documents.mindmap.expandAll') }}</q-tooltip>
        </q-btn>
        </div>
      </div>
      <div v-if="!readonly" class="editorial-toolbar-group" role="group" :aria-label="t('documents.mindmap.node')">
        <span class="editorial-toolbar-title">{{ t('documents.mindmap.node') }}</span>
        <div class="editorial-toolbar-row">
        <q-btn v-if="!active.body_html && active.value == null" flat dense :icon="editorialIcon('edit', 'edit')" :aria-label="t('documents.mindmap.rename')" @click="focusTitle(active.id)">
          <q-tooltip>{{ t('documents.mindmap.rename') }} ({{ t('documents.mindmapHelp.enter') }})</q-tooltip>
        </q-btn>
        <q-btn flat dense icon="notes" :aria-label="t('documents.mindmap.editNote')" @click="beginEdit(active.id, 'note')">
          <q-tooltip>{{ t('documents.mindmap.editNote') }} (F6)</q-tooltip>
        </q-btn>
        <q-btn v-if="!active.body_html || active.value != null" flat dense icon="emoji_emotions" :aria-label="t('documents.mindmap.icon')" @click="openIconPicker">
          <q-tooltip>{{ t('documents.mindmap.icon') }} (F2)</q-tooltip>
          <DocumentTagIconPicker v-model="iconOpen" :busy="false" :current-icon="iconNode?.icon" :save="saveIcon" document />
        </q-btn>
        <q-btn flat dense icon="edit_note" :aria-label="bodyLabel" @click="openBody(active.id)">
          <q-tooltip>{{ bodyLabel }} (Alt+Enter)</q-tooltip>
        </q-btn>
        <q-btn v-if="selection.some(node => node.checked == null)" flat dense icon="check_box_outline_blank"
          :aria-label="t('documents.mindmap.addCheckbox')" @click="setSelectionCheckboxes(true)">
          <q-tooltip>{{ t('documents.mindmap.addCheckbox') }} (F3)</q-tooltip>
        </q-btn>
        <q-btn v-if="selection.some(node => node.checked != null)" flat dense icon="indeterminate_check_box"
          :aria-label="t('documents.mindmap.removeCheckbox')" @click="setSelectionCheckboxes(false)">
          <q-tooltip>{{ t('documents.mindmap.removeCheckbox') }} (F3)</q-tooltip>
        </q-btn>
        <q-btn v-if="selection.some(node => node.value == null)" flat dense color="primary" icon="input"
          :aria-label="t('documents.mindmapValue.add')" @click="setSelectionValues(true)">
          <q-tooltip>{{ t('documents.mindmapValue.add') }} (F4)</q-tooltip>
        </q-btn>
        <q-btn v-if="selection.some(node => node.value != null)" flat dense color="negative" icon="remove_circle_outline"
          :aria-label="t('documents.mindmapValue.remove')" @click="setSelectionValues(false)">
          <q-tooltip>{{ t('documents.mindmapValue.remove') }} (F4)</q-tooltip>
        </q-btn>
        </div>
      </div>
      <div v-if="!readonly" class="editorial-toolbar-group" role="group" :aria-label="t('documents.mindmap.resources')">
        <span class="editorial-toolbar-title">{{ t('documents.mindmap.resources') }}</span>
        <div class="editorial-toolbar-row">
        <q-btn flat dense :icon="editorialIcon('link', 'link')" :aria-label="t('documents.mindmap.link')" :disable="!canAdd(active)" @click="openLinkDialog(active)">
          <q-tooltip>{{ t('documents.mindmap.link') }}</q-tooltip>
        </q-btn>
        <q-btn flat dense :icon="editorialIcon('resources.uploadFile', 'attach_file')" :aria-label="t('documents.mindmap.insertFile')"
          :loading="uploading" :disable="!canAdd(active)" @click="chooseFiles">
          <q-tooltip>{{ t('documents.mindmap.insertFile') }}</q-tooltip>
        </q-btn>
        <q-btn v-if="pickResources" flat dense :icon="editorialIcon('galarisLink', 'folder_open')" :aria-label="t('documents.mindmap.galaris')"
          :disable="!canAdd(active)" @click="chooseInternalResources">
          <q-tooltip>{{ t('documents.mindmap.galaris') }}</q-tooltip>
        </q-btn>
        </div>
      </div>
      <div v-if="documentTitle && !embedded" class="editorial-toolbar-group" role="group" :aria-label="t('documents.mindmap.export')">
        <span class="editorial-toolbar-title">{{ t('documents.mindmap.export') }}</span>
        <div class="editorial-toolbar-row">
          <q-btn flat dense :icon="editorialIcon('image', 'image')" :aria-label="t('documents.mindmapGraphic.png')" :disable="Boolean(graphicExport)"
            :loading="graphicExport === 'png'" @click="exportGraphic('png')">
            <q-tooltip>{{ t('documents.mindmapGraphic.png') }}</q-tooltip>
          </q-btn>
          <q-btn flat dense :icon="editorialIcon('print', 'print')" :aria-label="t('richEditor.print')" :disable="Boolean(graphicExport)"
            :loading="graphicExport === 'print'" @click="exportGraphic('print')">
            <q-tooltip>{{ t('richEditor.print') }}</q-tooltip>
          </q-btn>
          <q-btn flat dense :icon="editorialIcon('exportPdf', 'picture_as_pdf')" :aria-label="t('documents.exportFormatPdf')"
            @click="emit('export-document-pdf')">
            <q-tooltip>{{ t('documents.exportFormatPdf') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="exportBundle" flat dense icon="folder_zip" :aria-label="t('richEditor.resources.documentExportBundle')"
            :disable="Boolean(graphicExport)" :loading="graphicExport === 'zip'" @click="exportGraphic('zip')">
            <q-tooltip>{{ t('richEditor.resources.documentExportBundle') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="exportPdf && $q.screen.lt.md" flat dense icon="share" :aria-label="t('richEditor.share.action')" @click="openShare">
            <q-tooltip>{{ t('richEditor.share.action') }}</q-tooltip>
          </q-btn>
        </div>
      </div>
      </DocumentToolbarFrame>
      <div v-if="searchOpen && !activeBody" class="editorial-search-bar" role="search" :aria-label="t('richEditor.find')"
        @keydown.esc.stop.prevent="closeSearch">
        <q-input ref="searchInput" v-model="query" class="editorial-search-input" dense outlined :label="t('richEditor.find')" @keydown.enter.prevent="findNext" />
        <q-input v-if="!readonly" v-model="replacement" class="editorial-search-input" dense outlined :label="t('richEditor.replace')" @keydown.enter.prevent="replaceResults(false)" />
        <q-checkbox v-model="matchCase" dense :label="t('richEditor.matchCase')" />
        <q-checkbox v-model="wholeWords" dense :label="t('richEditor.wholeWords')" />
        <span role="status" aria-live="polite">{{ searchIndex < 0 ? matches.length : `${searchIndex + 1} / ${matches.length}` }}</span>
        <q-btn color="primary" dense outline :label="t('richEditor.next')" :disable="!matches.length" @click="findNext" />
        <template v-if="!readonly">
          <q-btn color="primary" dense outline :label="t('richEditor.replaceAll')" :disable="!matches.length" @click="replaceResults(true)" />
          <q-btn color="primary" dense :label="t('richEditor.replace')" :disable="!matches.length" @click="replaceResults(false)" />
        </template>
        <q-btn flat round dense icon="close" :aria-label="t('common.close')" @click="closeSearch" />
      </div>
      <div v-if="visibleSelection.size > 1" class="mindmap-selection-count" role="status">
        {{ t('documents.mindmapSelection.count', { count: selection.length }) }}
      </div>
      <div v-show="activeBody" ref="nodeToolbar" />
    </div>
    <div :id="canvasId" ref="canvas" class="mindmap-canvas" :class="{ 'mindmap-panning': panning }" :style="{ backgroundColor: canvasBackground }" :tabindex="-1"
      @focusin="onTreeFocus" @keydown="onTreeKeydown" @blur.self="leavingTree = false"
      @copy.capture="copyFromTree($event, 'copy')" @cut.capture="copyFromTree($event, 'cut')" @paste.capture="pasteIntoTree"
      @scroll="syncHorizontalScroll" @dragover="allowResourceDrop" @dragleave="leaveCanvas" @drop="dropResources"
      @mousedown.capture="preserveBranchFocus" @click.capture="selectWithModifiers"
      @pointerdown="onCanvasPointerDown" @pointermove="pointerMove" @pointerup="pointerEnd" @pointercancel="pointerEnd"
      @lostpointercapture="pointerEnd" @pointerleave="pointerLeave" @wheel="wheel">
      <div class="mindmap-plane" :style="planeStyle">
      <ul ref="stage" class="mindmap-root" :class="{ 'mindmap-root--connected': connectorPaths.length }"
        :style="stageStyle" role="tree" aria-multiselectable="true" :aria-label="t('documents.formats.mindmap')">
        <MindMapBranch :node="root" :children="children" :selected="visibleSelection" :focused="leavingTree ? '' : active.id" :folded="folded"
          :level="0" :document-title="documentTitle">
          <template #default="{ node, label, hasChildren, closed }">
            <div class="mindmap-node" :class="{ 'mindmap-node--cut': cutSubtree.ids.has(node.id), 'mindmap-rich-parent': (node.body_html || inspectedBody === node.id) && hasChildren,
              'mindmap-resource-only': resourceBodies.get(node.id)?.resourceOnly, 'mindmap-card-node': resourceBodies.get(node.id)?.standaloneCard,
              'mindmap-image-node': resourceBodies.get(node.id)?.imageOnly,
              'mindmap-link-node': resourceBodies.get(node.id)?.linkOnly && !node.note && !node.link && editing?.id !== node.id,
              'mindmap-embedded-node': resourceBodies.get(node.id)?.embeddedFrame, 'mindmap-checkable': node.checked != null }"
              :data-embedded-kind="resourceBodies.get(node.id)?.embeddedFrame?.kind"
              :data-drop-placement="dropTarget?.id === node.id ? dropTarget.placement : undefined"
              :style="{ '--map-resource-border': resourceBodies.get(node.id)?.embeddedFrame?.borderColor }"
              @dragover="hoverBranch($event, node)" @dragleave="leaveBranch($event, node.id)" @drop="dropBranch($event, node)">
              <q-checkbox v-if="node.checked != null" dense size="sm" color="primary" class="mindmap-node-checkbox"
                :model-value="node.checked" :disable="readonly" :aria-label="t('documents.mindmap.checkbox', { node: label })"
                @update:model-value="setCheckbox(node.id, $event)" />
              <div v-if="node.value != null || (!node.body_html && inspectedBody !== node.id)" class="mindmap-node-line" @click.self="selectTitle($event, node.id)">
                <LibraryIcon v-if="node.icon" :icon="node.icon" size="18px" />
                <span v-if="!readonly && node.id === editingTitle?.id" key="editable" v-text="editingTitle.initial"
                  class="mindmap-label mindmap-title" contenteditable="plaintext-only" role="textbox" aria-multiline="false" tabindex="-1"
                  :aria-label="t('documents.mindmap.title')"
                  @focus="revealTitle(node.id)" @blur="finishTitle(node.id)" @keydown="onTitleKeydown($event, node.id)" />
                <span v-else key="label" class="mindmap-label"
                  :draggable="!readonly && node.parent !== null"
                  @click="selectTitle($event, node.id)"
                  @dblclick="editValueNodeTitle($event, node)"
                  @dragstart="startDrag($event, node)" @dragend="stopDrag">{{ node.title }}</span>
                <template v-if="node.value != null">
                  <input class="mindmap-value-input" type="text"
                    :value="node.value" :readonly="readonly" :maxlength="maxValueLength"
                    :tabindex="!readonly && selectedIds.has(node.id) ? 0 : -1"
                    :aria-label="t('documents.mindmapValue.field', { node: label })"
                    @focus="selectValue(node.id)" @blur="history.endGroup()"
                    @input="updateNodeValue($event, node.id)" @compositionend="updateNodeValue($event, node.id)"
                    @keydown="onValueKeydown($event, node)" />
                  <q-btn flat round dense color="primary" icon="content_copy" size="sm" :disable="!node.value"
                    :tabindex="selectedIds.has(node.id) ? 0 : -1"
                    :aria-label="t('documents.mindmapValue.copy')" @click="copyNodeValue(node.value)">
                    <q-tooltip>{{ t('documents.mindmapValue.copy') }}</q-tooltip>
                  </q-btn>
                </template>
                <q-btn v-if="connectorsByNode.has(node.id)" flat round dense color="primary" icon="hub" size="sm"
                  :tabindex="selectedIds.has(node.id) ? 0 : -1"
                  :aria-label="t('documents.mindmapConnectors.forNode', { node: label })" @click="openConnectors(node.id)" />
                <q-btn v-if="node.note || node.link" flat round dense icon="notes" size="sm" tabindex="-1"
                  :aria-label="t('documents.mindmap.details')" :aria-expanded="detailsOpen(node)"
                  @click="toggleDetails(node.id)" />
                <q-btn v-if="hasChildren" flat round dense :icon="closed ? 'add' : 'remove'" size="sm" tabindex="-1"
                  :aria-label="t(closed ? 'documents.mindmap.expand' : 'documents.mindmap.collapse', { node: label })"
                  :aria-expanded="!closed" @click="toggleFold(node.id)" />
              </div>
              <div v-if="detailsOpen(node) || inspectedBody === node.id || editing?.id === node.id" class="mindmap-details"
                @click.capture="selectReference($event, node.id)" @click.self="node.body_html && selectBody($event, node.id)">
                <p v-if="node.note && !(editing?.id === node.id && editing.field === 'note')">{{ node.note }}</p>
                <EditorialContent v-if="node.link && standaloneBody !== node.id && !(editing?.id === node.id && editing.field === 'link')"
                  class="mindmap-standalone-link" :content="mindMapLinkHtml(node.link)" profile="document" />
                <div v-if="node.body_html || inspectedBody === node.id" class="mindmap-rich-body"
                  :class="{ 'mindmap-inspecting-resource': inspectedPreview?.id === node.id, 'mindmap-editing-body': activeBody === node.id }">
                  <RichTextEditor v-if="node.id === activeSurface && nodeToolbar && contextToolbar" ref="bodyEditor" :key="node.id"
                    :model-value="oversizedBodies.get(node.id) ?? bodyMarkup(node)"
                    profile="document" toolbar-mode="full" surface="embedded" :toolbar-target="nodeToolbar"
                    :toolbar-document-navigation="Boolean(managedFullscreen)"
                    :context-toolbar-target="activeBody ? undefined : contextToolbar"
                    :allow-paragraph-insertion="Boolean(activeBody)"
                    :aria-label="t('documents.mindmap.richContent')" min-height="2.5rem" max-height="37dvh" image-width-unit="px" :allow-image-border="false" auto-grow
                    :attachments="attachments" :resource-agent-id="resourceAgentId" :pick-resources="pickResources"
                    :create-link-card="createLinkCard" :upload-file="uploadFile" :upload-image="uploadImage" :import-image="importImage"
                    :resolve-image="resolveImage" :render-media="inspectedPreview?.id !== node.id" :preview-actions="selectedPreviewActions"
                    :context-focus-within="focusWithinPreview"
                    @beforeinput="editingBody = node.id" @keydown.capture="typeInInspectedBody($event, node.id)" @request-exit="closeBody"
                    @open-attachment="(documentId, attachmentId) => emit('open-attachment', documentId, attachmentId)"
                    @update:model-value="updateBody(node.id, $event)">
                    <template #toolbar-leading>
                      <q-btn flat dense icon="arrow_back" :aria-label="t('documents.mindmap.finishRichContent')" @click="closeBody">
                        <q-tooltip>{{ t('documents.mindmap.finishRichContent') }} (Esc)</q-tooltip>
                      </q-btn>
                    </template>
                  </RichTextEditor>
                  <EditorialContent v-if="node.id !== activeSurface || inspectedPreview?.id === node.id" :content="bodyMarkup(node)" profile="document"
                    :resource-agent-id="resourceAgentId" :resolve-image="resolveImage" :register-reference-actions="registerPreviewActions"
                    :resize-reference="readonly ? undefined : (index, uri, size) => resizeNodeEmbed(node.id, index, uri, size)"
                    :draggable="!readonly && node.parent !== null" @click="selectBody($event, node.id)"
                    @dragstart="startDrag($event, node)" @dragend="stopDrag" />
                  <q-banner v-if="node.id === activeSurface && oversizedBodies.has(node.id)" dense class="text-negative" role="alert">{{ t('documents.mindmap.bodyTooLarge') }}</q-banner>
                </div>
                <q-input v-if="editing?.id === node.id" class="mindmap-detail-input" dense borderless
                  :type="editing.field === 'note' ? 'textarea' : 'text'" :rows="3"
                  :model-value="editing.value" :label="t(`documents.mindmap.${editing.field}`)" :maxlength="fieldLengths[editing.field]"
                  @update:model-value="updateDraft" @blur="commitDraft" @keydown="onEditKeydown" />
              </div>
              <q-btn v-if="node.value == null && (node.body_html || inspectedBody === node.id) && hasChildren" class="mindmap-rich-fold" flat round dense :icon="closed ? 'add' : 'remove'" size="sm" tabindex="-1"
                :aria-label="t(closed ? 'documents.mindmap.expand' : 'documents.mindmap.collapse', { node: label })"
                :aria-expanded="!closed" @click="toggleFold(node.id)" />
              <q-select v-if="!readonly && changingParent === node.id" class="mindmap-details"
                dense outlined emit-value map-options autofocus
                :model-value="node.parent" :options="parents" :label="t('documents.mindmap.parent')"
                @update:model-value="chooseParent" @keydown.esc.stop.prevent="changingParent = null; focusNode(node.id)" />
            </div>
          </template>
        </MindMapBranch>
      </ul>
      <svg v-if="connectorPaths.length" class="mindmap-connectors" :style="stageStyle" width="1" height="1">
        <defs>
          <marker :id="connectorMarker" viewBox="0 0 8 8" markerWidth="6" markerHeight="6" refX="8" refY="4" orient="auto">
            <path class="mindmap-connector-arrow" d="M 0 0 L 8 4 L 0 8 Z" />
          </marker>
        </defs>
        <g v-for="connector in connectorPaths" :key="connector.key" role="button" tabindex="-1"
          :data-connector-key="connector.key"
          :class="{ 'mindmap-connector--active': connectorNavigation?.key === connector.key }"
          :aria-label="connectorNavigation?.key === connector.key ? connectorNavigationLabel : t('documents.mindmapConnectors.openNamed', { label: connector.label })"
          @pointerdown.stop @click="openConnectorByKey(connector.key)"
          @keydown="onConnectorNavigationKeydown($event, connector.key)"
          @focusout="leaveConnectorNavigation(connector.key)"
          @keydown.enter.space.stop.prevent="openConnectorByKey(connector.key)">
          <path class="mindmap-connector-line" :d="connector.path" :marker-end="`url(#${connectorMarker})`" />
          <path class="mindmap-connector-hit" :d="connector.path" />
          <text :x="connector.x" :y="connector.y" :text-anchor="connector.anchor" class="mindmap-connector-label">{{ connector.label }}</text>
        </g>
      </svg>
      </div>
    </div>
    <input ref="horizontalBar" class="mindmap-scrollbar" type="range" min="0" :max="horizontalLimit" :value="horizontalPosition"
      :style="{ '--mindmap-scroll-thumb': `${horizontalThumb}%` }" :aria-label="t('documents.mindmap.scrollHorizontal')"
      :aria-controls="canvasId" @input="onHorizontalInput" />
    <input v-if="!readonly" ref="fileInput" type="file" multiple hidden @change="filesChosen" />
    <q-dialog v-model="themesOpen" :aria-label="t('documents.mindmapThemes.title')">
      <q-card class="galaris-dialog-card" style="width: 360px; max-width: 95vw">
        <DialogHeader :title="t('documents.mindmapThemes.title')" :close-label="t('common.close')" />
        <q-card-section class="galaris-dialog-body">
          <div class="mindmap-theme-options" role="radiogroup" :aria-label="t('documents.mindmapThemes.title')">
            <q-radio v-for="(tones, id) in themePalettes" :key="id" v-model="themeDraft" :val="id"
              :aria-label="t(`documents.mindmapThemes.${id}`)">
              <span class="mindmap-theme-option">
                {{ t(`documents.mindmapThemes.${id}`) }}
                <span class="mindmap-theme-swatches" aria-hidden="true">
                  <span v-for="(tone, index) in tones" :key="index" class="mindmap-theme-swatch" :style="swatch(tone)" />
                </span>
              </span>
            </q-radio>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
          <q-btn color="primary" :label="t('richEditor.apply')" @click="applyTheme" />
        </q-card-actions>
      </q-card>
    </q-dialog>
    <q-dialog v-model="backgroundOpen" :aria-label="t('richEditor.backgroundColor')">
      <q-card class="galaris-dialog-card" style="width: 360px; max-width: 95vw">
        <DialogHeader :title="t('richEditor.backgroundColor')" :close-label="t('common.close')" />
        <q-card-section class="galaris-dialog-body">
          <q-color :model-value="backgroundDraft" default-value="#ffffff" default-view="spectrum" format-model="hex"
            class="full-width" no-header-tabs no-footer @update:model-value="previewBackground" />
          <q-btn class="q-mt-md" outline color="primary" :label="t('documents.mindmapThemes.defaultBackground')"
            :disable="!backgroundDraft" @click="backgroundDraft = undefined" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
          <q-btn color="primary" :label="t('richEditor.apply')" @click="applyBackground" />
        </q-card-actions>
      </q-card>
    </q-dialog>
    <DocumentPdfShareDialog v-if="exportPdf && !embedded" v-model="shareOpen" :title="documentTitle" :url="documentUrl" :create-file="createShareFile" />
    <q-dialog v-model="linkDialogOpen" :aria-label="t('documents.mindmap.link')">
      <q-card class="galaris-dialog-card" style="width: 480px; max-width: 95vw">
        <DialogHeader :title="t('documents.mindmap.link')" :close-label="t('common.close')" />
        <q-form @submit="insertLinkChild">
          <q-card-section class="galaris-dialog-body q-gutter-sm">
            <q-input v-model="linkDraft.url" outlined autofocus :label="t('richEditor.uri')" />
            <q-input v-model="linkDraft.title" outlined :maxlength="titleLength" :label="t('richEditor.linkText')" />
          </q-card-section>
          <q-card-actions align="right">
            <q-btn outline color="primary" v-close-popup :label="t('common.cancel')" />
            <q-btn type="submit" color="primary" :disable="!linkUri" :label="t('documents.mindmap.link')" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
    <q-dialog :model-value="Boolean(connectorNode)" :aria-label="t('documents.mindmapConnectors.title')"
      @update:model-value="connectorNodeId = undefined">
      <q-card class="galaris-dialog-card" style="width: 520px; max-width: 95vw">
        <DialogHeader :title="t('documents.mindmapConnectors.title')" :close-label="t('common.close')" />
        <q-card-section v-if="connectorNode" class="galaris-dialog-body q-gutter-sm">
          <q-form v-if="connectorTargetNode && !readonly" class="q-gutter-sm" @submit="saveConnector">
            <div class="text-subtitle1">{{ nodeLabel(connectorNode) }} → {{ nodeLabel(connectorTargetNode) }}</div>
            <q-input v-model="connectorLabel" dense outlined autofocus :maxlength="maxConnectorLabelLength"
              :label="t('documents.mindmapConnectors.label')" />
            <div class="row justify-end q-gutter-sm">
              <q-btn v-if="connectorEdit" color="negative" :label="t('documents.mindmapConnectors.remove')"
                @click="connectorRemoval = connectorEdit" />
              <q-btn type="submit" color="primary" :disable="!canSaveConnector"
                :label="t(connectorEdit ? 'documents.mindmapConnectors.rename' : 'documents.mindmapConnectors.add')" />
            </div>
          </q-form>
          <template v-else>
            <div class="text-subtitle1">{{ nodeLabel(connectorNode) }}</div>
            <q-list v-if="currentConnectors.length" separator>
              <q-item v-for="({ connector, other }, index) in currentConnectors" :key="connectorKey(connector)">
                <q-item-section>
                  <q-item-label>{{ connector.label }}</q-item-label>
                  <q-item-label caption>
                    {{ t(connector.source === connectorNode.id ? 'documents.mindmapConnectors.toNode' : 'documents.mindmapConnectors.fromNode', { node: nodeLabel(other) }) }}
                  </q-item-label>
                </q-item-section>
                <q-item-section side>
                  <div class="row no-wrap">
                    <q-btn flat round dense color="primary" icon="arrow_forward"
                      :data-autofocus="index === 0 || undefined"
                      :aria-label="t('documents.mindmapConnectors.jumpTo', { node: nodeLabel(other) })" @click="jumpToConnector(other.id)" />
                    <q-btn v-if="!readonly" flat round dense color="primary" icon="edit"
                      :aria-label="t('documents.mindmapConnectors.renameNamed', { label: connector.label })" @click="editConnector(connector)" />
                    <q-btn v-if="!readonly" flat round dense color="negative" icon="delete"
                      :aria-label="t('documents.mindmapConnectors.removeNamed', { label: connector.label })" @click="connectorRemoval = connector" />
                  </div>
                </q-item-section>
              </q-item>
            </q-list>
            <div v-else>{{ t(readonly ? 'documents.mindmapConnectors.empty' : 'documents.mindmapConnectors.selectTwo') }}</div>
          </template>
        </q-card-section>
      </q-card>
    </q-dialog>
    <q-dialog data-confirmation :model-value="Boolean(connectorRemoval)" :aria-label="t('documents.mindmapConnectors.remove')"
      @update:model-value="connectorRemoval = undefined">
      <q-card class="galaris-dialog-card" style="width: 480px; max-width: 95vw">
        <DialogHeader :title="t('documents.mindmapConnectors.remove')" :close-label="t('common.close')" />
        <q-card-section class="galaris-dialog-body">
          {{ t('documents.mindmapConnectors.confirmRemove', { label: connectorRemoval?.label ?? '' }) }}
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
          <q-btn data-autofocus color="negative" :label="t('documents.mindmapConnectors.remove')" @click="removeConnector" />
        </q-card-actions>
      </q-card>
    </q-dialog>
    <q-dialog data-confirmation :model-value="pendingRemove !== null" :aria-label="removeLabel"
      @update:model-value="pendingRemove = null">
      <q-card class="galaris-dialog-card" style="width: 480px; max-width: 95vw">
        <DialogHeader :title="removeLabel" :close-label="t('common.close')" />
        <q-card-section class="galaris-dialog-body">
          {{ selectionRoots.length > 1 ? t('documents.mindmapSelection.confirmRemove', { count: selectionRoots.length }) : t('documents.mindmap.confirmRemove') }}
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
          <q-btn data-autofocus color="negative" :label="removeLabel" @click="removeBranches" />
        </q-card-actions>
      </q-card>
    </q-dialog>
    <q-dialog data-confirmation :model-value="Boolean(pendingValueRemoval)" :aria-label="t('documents.mindmapValue.remove')"
      @update:model-value="pendingValueRemoval = undefined">
      <q-card class="galaris-dialog-card" style="width: 480px; max-width: 95vw">
        <DialogHeader :title="t('documents.mindmapValue.remove')" :close-label="t('common.close')" />
        <q-card-section class="galaris-dialog-body">{{ t('documents.mindmapValue.confirmRemove') }}</q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
          <q-btn data-autofocus color="negative" :label="t('documents.mindmapValue.remove')" @click="confirmValueRemoval" />
        </q-card-actions>
      </q-card>
    </q-dialog>
    <q-dialog v-model="helpOpen" :aria-label="t('documents.mindmapHelp.title')">
      <q-card class="galaris-dialog-card" style="width: 480px; max-width: 95vw">
        <DialogHeader :title="t('documents.mindmapHelp.title')" :close-label="t('common.close')" />
        <q-card-section class="galaris-dialog-body">
          <q-markup-table flat dense wrap-cells>
            <tbody>
              <tr v-for="[label, keys] in keyboardShortcuts" :key="label"><td>{{ label }}</td><td class="text-right"><kbd>{{ keys }}</kbd></td></tr>
            </tbody>
          </q-markup-table>
        </q-card-section>
      </q-card>
    </q-dialog>
  </section>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, provide, ref, shallowReactive, shallowRef, useId, useTemplateRef, watch } from 'vue'
import { colors, copyToClipboard, useQuasar, type QInput } from 'quasar'
import { useI18n } from 'vue-i18n'
import { DialogHeader, documentFullscreenKey, documentResourceHtml, EditorialContent, LibraryIcon, RichTextEditor, editorialIcon, richLinkDefaultMode, solaire, solaireCss, type SolaireColor } from '@/core/util'
import { createDocumentPdf, documentReferenceCards, DocumentPdfShareDialog, DocumentToolbarFrame, documentUriFromLink, downloadDocumentBundle, mountImageResize, referenceMode, referenceUri, resourceBlock, resourceLinkElement, saveBlobAsResource, writeDocumentEmbedSize, type DocumentEmbedSize, type DocumentReferenceAction } from '@/core/util/facade'
import DocumentTagIconPicker from '../components/DocumentTagIconPicker.vue'
import MindMapBranch from './MindMapBranch.vue'
import { mindMapDroppedResources, mindMapLinkHtml, mindMapOutline, mindMapParagraphHtml, mindMapReferenceUri, mindMapResourceBody } from './content'
import { connectorKey, isHexColor, maxConnectorLabelLength, maxConnectors, maxDepth, maxNodes, maxValueLength, mindMapNodeLabel, nodesByParent, parseMindMap, type MindMapConnector, type MindMapNode } from './model'
import { replaceMindMapMatches, searchMindMap, type MindMapMatch } from './search'
import { useMindMapHistory } from './useMindMapHistory'
import { useMindMapConnectors } from './useMindMapConnectors'
import { useMindMapViewport } from './useMindMapViewport'

defineOptions({ inheritAttrs: false })
type UploadResource = (file: File, signal: AbortSignal, progress: (value: number) => void) => Promise<string>
const props = defineProps<{
  readonly?: boolean
  embedded?: boolean
  documentTitle?: string
  documentUrl?: string
  exportBundle?: (html: string, signal: AbortSignal) => Promise<Blob>
  exportPdf?: (html: string, signal: AbortSignal) => Promise<Blob>
  attachments?: { uri: string; name: string; size: number; mediaType?: string }[]
  resourceAgentId?: number | null
  pickResources?: () => Promise<string>
  createLinkCard?: (url: string) => Promise<string>
  uploadFile?: UploadResource
  uploadImage?: UploadResource
  importImage?: (url: string, signal: AbortSignal) => Promise<string>
  resolveImage?: (documentId: string, attachmentId: string, signal?: AbortSignal) => Promise<Blob>
}>()
const emit = defineEmits<{ 'open-attachment': [documentId: string, attachmentId: string]; 'export-document-pdf': [] }>()
const model = defineModel<string>({ required: true })
const history = useMindMapHistory(model)
const { undo, redo } = history
const { t } = useI18n()
const $q = useQuasar()
const canvasId = useId()
const connectorMarker = useId()
const canvas = useTemplateRef<HTMLElement>('canvas')
const stage = useTemplateRef<HTMLElement>('stage')
const toolbar = useTemplateRef<HTMLElement>('toolbar')
const mapToolbar = useTemplateRef<InstanceType<typeof DocumentToolbarFrame>>('mapToolbar')
const contextToolbar = computed(() => mapToolbar.value?.element ?? undefined)
const horizontalBar = useTemplateRef<HTMLElement>('horizontalBar')
const managedFullscreen = props.embedded ? null : inject(documentFullscreenKey, null)
const fullscreen = managedFullscreen ?? ref(false)
const standaloneFullscreen = computed(() => !managedFullscreen && fullscreen.value)
if (!managedFullscreen && !props.embedded) provide(documentFullscreenKey, fullscreen)
const fullscreenLabel = computed(() => t(fullscreen.value ? 'fullscreenPreview.exitFullscreen' : 'fullscreenPreview.fullscreen'))
const {
  percentage, planeStyle, stageStyle, horizontalLimit, horizontalPosition, horizontalThumb, syncHorizontalScroll,
  setHorizontalScroll, panning, zoomStep, reset, fit, wheel, pointerDown, pointerMove, pointerEnd, reveal,
} = useMindMapViewport(canvas, stage, toolbar, horizontalBar, fullscreen)
function onHorizontalInput(event: Event): void {
  if (event.target instanceof HTMLInputElement) setHorizontalScroll(event.target.valueAsNumber)
}
function pointerLeave(event: PointerEvent): void {
  if (!canvas.value?.hasPointerCapture(event.pointerId)) pointerEnd(event)
}
const nodeToolbar = useTemplateRef<HTMLElement>('nodeToolbar')
const bodyEditor = useTemplateRef<InstanceType<typeof RichTextEditor>>('bodyEditor')
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')
const uploading = ref(false)
const graphicExport = ref<'png' | 'print' | 'zip'>()
const shareOpen = ref(false)
let graphicRequest: AbortController | undefined
let uploadRequest: AbortController | undefined
let fileParent: string | undefined
let disposed = false
const inspectedBody = ref<string>()
const standaloneBody = ref<string>()
const pendingReference = shallowRef<{ id: string; uri: string; index: number; kind: 'link' | 'image' | 'card' | 'table' }>()
const previewSelection = shallowRef<{ id: string; card: HTMLElement | null; image?: HTMLImageElement | null }>()
const previewActions = shallowReactive(new WeakMap<HTMLElement, readonly DocumentReferenceAction[]>())
const pendingBody = shallowRef<{ id: string; text: string }>()
const oversizedBodies = ref(new Map<string, string>())
const editingBody = ref<string>()
const iconOpen = ref(false)
const pendingValueRemoval = shallowRef<ReadonlySet<string>>()
const helpOpen = ref(false)
const linkDialogOpen = ref(false)
const linkDraft = ref({ parent: '', url: '', title: '' })
const linkUri = computed(() => mindMapReferenceUri(linkDraft.value.url))
const themesOpen = ref(false)
const backgroundOpen = ref(false)
const themePalettes = {
  solaire: ['gray', 'iris', 'green', 'salmon'],
  ocean: ['blue', 'cyan', 'iris', 'blue'],
  forest: ['green', 'green', 'yellow', 'orange'],
  monochrome: ['gray', 'gray', 'gray', 'gray'],
} as const satisfies Record<string, readonly [SolaireColor, SolaireColor, SolaireColor, SolaireColor]>
type ThemeId = keyof typeof themePalettes
const themeDraft = ref<ThemeId>('solaire')
const backgroundDraft = ref<string>()
const themeVersion = 1
const iconId = ref<string>()
const connectorNodeId = ref<string>()
const connectorRemoval = shallowRef<MindMapConnector>()
const connectorEdit = shallowRef<MindMapConnector>()
const connectorNavigation = shallowRef<{ origin: string; key: string; destination: string; label: string }>()
const connectorTarget = ref<string>()
const connectorLabel = ref('')
const selected = ref('')
type BranchSelection = { kind: 'all' } | { kind: 'range'; anchor: string } | { kind: 'nodes'; anchor: string; ids: ReadonlySet<string> }
const branchSelection = shallowRef<BranchSelection>()
const selectionAnchor = computed(() => branchSelection.value?.kind === 'all' ? undefined : branchSelection.value?.anchor)
const searchOpen = ref(false)
const searchInput = useTemplateRef<QInput>('searchInput')
const query = ref(''), replacement = ref('')
const matchCase = ref(false), wholeWords = ref(false)
const searchIndex = ref(-1)
let selectedOnPointerDown = ''
let pressedBranch: Element | null = null
const folded = ref(new Set<string>())
const details = ref(new Set<string>())
const pendingRemove = ref<string | null>(null)
const changingParent = ref<string | null>(null)
const leavingTree = ref(false)
const mapFocused = ref(false)
const dragged = shallowRef<string[]>()
type BranchPlacement = 'before' | 'inside' | 'after'
const dropTarget = shallowRef<{ id: string; placement: BranchPlacement }>()
type BranchClipboard = { token: string; text: string } & (
  { mode: 'copy'; nodes: MindMapNode[]; connectors: MindMapConnector[]; height: number }
  | { mode: 'cut'; ids: string[] } | { mode: 'inactiveCut' }
)
const branchClipboardMime = 'application/x-galaris-mindmap-clipboard'
const branchClipboard = shallowRef<BranchClipboard>()
const titleLength = 500
const fieldLengths = { note: 16000, link: 2048 }
type Field = keyof typeof fieldLengths
const editing = ref<{ id: string; field: Field; value: string } | null>(null)
const editingTitle = ref<{ id: string; initial: string }>()
const map = computed(() => parseMindMap(model.value))
const themeShade = computed(() => $q.dark.isActive ? 'dark' : 'light')
const savedTheme = computed<ThemeId>(() => {
  const theme = map.value?.theme
  return theme?.version === themeVersion && Object.hasOwn(themePalettes, theme.id) ? theme.id as ThemeId : 'solaire'
})
const savedBackground = computed(() => {
  const color = map.value?.background_color
  if (isHexColor(color)) return color.toLowerCase()
  return color && Object.hasOwn(solaire, color) ? solaire[color as SolaireColor][themeShade.value].toLowerCase() : undefined
})
const canvasBackground = computed(() => backgroundOpen.value ? backgroundDraft.value : savedBackground.value)
const mapThemeStyle = computed(() => {
  const tone = canvasBackground.value
  const ink = tone ? (colors.luminosity(tone) > .179 ? 'black' : 'white') : undefined
  return {
    ...Object.fromEntries(themePalettes[themesOpen.value ? themeDraft.value : savedTheme.value].flatMap((color, level) => [
      [`--map-level-${level}-accent`, solaireCss[color].accent],
      [`--map-level-${level}-tint`, solaireCss[color][themeShade.value]],
    ])),
    '--map-canvas-ink': ink ? `color-mix(in srgb, ${ink} 60%, transparent)` : undefined,
  }
})

async function exportGraphic(kind: 'png' | 'print' | 'zip'): Promise<void> {
  const title = props.documentTitle
  if (!title || graphicRequest || !canvas.value) return
  const exportBundle = props.exportBundle
  if (kind === 'zip' && !exportBundle) return
  if (!props.readonly) commitDraft()
  await nextTick()
  const current = map.value
  const surface = canvas.value
  if (!current || !surface || graphicRequest || disposed) return
  const controller = new AbortController()
  graphicRequest = controller
  graphicExport.value = kind
  const signal = controller.signal
  const appearance = {
    background: canvasBackground.value ?? getComputedStyle(surface).getPropertyValue('--map-neutral').trim(),
    dark: $q.dark.isActive,
    theme: mapThemeStyle.value,
  }
  try {
    const { prepareMindMapGraphic, graphicHtml, mindMapPng, printMindMap } = await import('./graphic')
    const archive = kind === 'zip' ? { attachments: props.attachments ?? [], heading: t('richEditor.resources.attachments') } : undefined
    const graphic = await prepareMindMapGraphic(current, title, appearance, signal, props.resourceAgentId ?? null, imageResolver(signal), archive)
    if (kind === 'print') await printMindMap(graphic, title, signal)
    else if (kind === 'zip' && exportBundle) await downloadDocumentBundle(graphicHtml(graphic.document), title, signal, exportBundle)
    else {
      const image = await mindMapPng(graphic, signal)
      signal.throwIfAborted()
      saveBlobAsResource(image, `${title.replace(/[\\/:*?"<>|]/g, '-')}.png`)
    }
  } catch {
    if (!signal.aborted) $q.notify({ type: 'negative', message: t(kind === 'print' ? 'richEditor.printFailed' : 'documents.formatExportFailed') })
  } finally {
    graphicRequest = undefined
    graphicExport.value = undefined
  }
}

function imageResolver(signal: AbortSignal) {
  const resolveImage = props.resolveImage
  return resolveImage && ((documentId: string, attachmentId: string) => resolveImage(documentId, attachmentId, signal))
}

function openShare(): void {
  commitDraft()
  shareOpen.value = true
}

function createShareFile(signal: AbortSignal): Promise<File> {
  if (!map.value || !props.exportPdf || !props.documentTitle) return Promise.reject(new Error('PDF export unavailable'))
  return createDocumentPdf(mindMapOutline(map.value), props.documentTitle, signal, props.exportPdf, imageResolver(signal))
}

function swatch(tone: SolaireColor): { background: string; borderColor: string } {
  return { background: solaireCss[tone][themeShade.value], borderColor: solaireCss[tone].accent }
}

function openThemes(): void {
  themeDraft.value = savedTheme.value
  themesOpen.value = true
}

function applyTheme(): void {
  const current = map.value
  if (!props.readonly && current) {
    const theme = themeDraft.value === savedTheme.value ? current.theme : { id: themeDraft.value, version: themeVersion }
    if (theme !== current.theme) history.record({ ...current, theme })
  }
  themesOpen.value = false
}

function openBackground(): void {
  backgroundDraft.value = savedBackground.value
  backgroundOpen.value = true
}

function previewBackground(color: string | null): void {
  if (isHexColor(color)) backgroundDraft.value = color.toLowerCase()
}

function applyBackground(): void {
  const current = map.value
  if (!props.readonly && current && backgroundDraft.value !== savedBackground.value) {
    history.record({ ...current, background_color: backgroundDraft.value })
  }
  backgroundOpen.value = false
}

function toggleFullscreen(): void {
  const focused = canvas.value?.ownerDocument.activeElement
  fullscreen.value = !fullscreen.value
  if (!managedFullscreen) void nextTick(() => { if (focused instanceof HTMLElement) focused.focus({ preventScroll: true }) })
}

function onFullscreenEscape(event: KeyboardEvent): void {
  if (managedFullscreen || !fullscreen.value || event.defaultPrevented || event.isComposing) return
  event.preventDefault()
  event.stopPropagation()
  toggleFullscreen()
}
const resourceBodies = computed(() => new Map(map.value?.nodes.flatMap(node => node.body_html ? [[node.id, mindMapResourceBody(node.body_html)] as const] : [])))
const children = computed(() => nodesByParent(map.value?.nodes ?? []))
const root = computed(() => children.value.get(null)?.[0])
const byId = computed(() => new Map(map.value?.nodes.map(node => [node.id, node])))
const iconNode = computed(() => byId.value.get(iconId.value ?? ''))
const active = computed(() => byId.value.get(selected.value) ?? root.value ?? { id: '', parent: null, title: '' })
function nodesInBranchOrder(collapsed?: ReadonlySet<string>): MindMapNode[] {
  const nodes: MindMapNode[] = []
  function visit(node: MindMapNode): void {
    nodes.push(node)
    if (!collapsed?.has(node.id)) children.value.get(node.id)?.forEach(visit)
  }
  if (root.value) visit(root.value)
  return nodes
}
const visibleNodes = computed(() => nodesInBranchOrder(folded.value))
const orderedNodes = computed(() => nodesInBranchOrder())
const connectors = computed(() => map.value?.connectors ?? [])
const connectorPaths = useMindMapConnectors(stage, visibleNodes, connectors)
type ConnectedNode = { connector: MindMapConnector; other: MindMapNode }
const connectorsByNode = computed(() => {
  const index = new Map<string, ConnectedNode[]>()
  function add(node: string, connector: MindMapConnector, other: MindMapNode): void {
    const links = index.get(node)
    if (links) links.push({ connector, other })
    else index.set(node, [{ connector, other }])
  }
  for (const connector of connectors.value) {
    const source = byId.value.get(connector.source), target = byId.value.get(connector.target)
    if (source && target) {
      add(source.id, connector, target)
      add(target.id, connector, source)
    }
  }
  return index
})
const connectorNavigationLabel = computed(() => {
  const choice = connectorNavigation.value
  const node = choice ? byId.value.get(choice.destination) : undefined
  return choice && node ? t('documents.mindmapConnectors.navigateNamed', { label: choice.label, node: nodeLabel(node) }) : undefined
})
const connectorNode = computed(() => byId.value.get(connectorNodeId.value ?? ''))
const connectorTargetNode = computed(() => byId.value.get(connectorTarget.value ?? ''))
const currentConnectors = computed(() => connectorsByNode.value.get(connectorNode.value?.id ?? '') ?? [])
const formConnector = computed(() => currentConnectors.value.find(link => link.other.id === connectorTargetNode.value?.id)?.connector)
const canSaveConnector = computed(() => {
  const label = connectorLabel.value.trim()
  if (props.readonly || !connectorTargetNode.value || !label || Array.from(label).length > maxConnectorLabelLength) return false
  if (!connectorEdit.value) return connectors.value.length < maxConnectors && !formConnector.value
  return formConnector.value?.label === connectorEdit.value.label && label !== connectorEdit.value.label
})
const selection = computed(() => {
  const currentSelection = branchSelection.value
  if (currentSelection?.kind === 'all') return orderedNodes.value
  if (currentSelection?.kind === 'nodes') return orderedNodes.value.filter(node => currentSelection.ids.has(node.id))
  const nodes = visibleNodes.value
  const anchor = nodes.findIndex(node => node.id === selectionAnchor.value)
  const current = nodes.findIndex(node => node.id === active.value.id)
  return anchor < 0 || current < 0 ? [active.value] : nodes.slice(Math.min(anchor, current), Math.max(anchor, current) + 1)
})
const selectionIds = computed(() => new Set(selection.value.map(node => node.id)))
const selectedValues = computed(() => selection.value.flatMap(node => node.value
  ? [{ title: nodeLabel(node), value: node.value }]
  : []))
const selectedIds = computed(() => leavingTree.value ? new Set<string>() : selectionIds.value)
const visibleSelection = computed(() => mapFocused.value ? selectedIds.value : new Set<string>())
const selectionRoots = computed(() => branchRoots(selection.value))
const canMoveSelection = computed(() => selectionRoots.value.length > 0 && selectionRoots.value.every(node => node.parent !== null))
const removeLabel = computed(() => t(selectionRoots.value.length > 1 ? 'documents.mindmapSelection.remove' : 'documents.mindmap.remove'))
const activeBody = computed(() => !props.readonly && !leavingTree.value && editingBody.value === active.value.id && (active.value.body_html || inspectedBody.value === active.value.id) ? active.value.id : undefined)
watch(activeBody, (id, previous) => { if (previous && previous !== id) history.endGroup() }, { flush: 'sync' })
const matches = computed(() => searchOpen.value ? searchMindMap(orderedNodes.value, query.value, matchCase.value, wholeWords.value) : [])
watch([query, matchCase, wholeWords, map], () => { searchIndex.value = -1 })
const activeSurface = computed(() => activeBody.value ?? (!props.readonly && !leavingTree.value ? inspectedBody.value : undefined))
const inspectedPreview = computed(() => previewSelection.value?.id === activeSurface.value && !activeBody.value ? previewSelection.value : undefined)
const selectedPreviewActions = computed(() => inspectedPreview.value?.card ? previewActions.get(inspectedPreview.value.card) : undefined)
const bodyLabel = computed(() => t(active.value.body_html ? 'documents.mindmap.richContent' : 'documents.mindmap.makeRich'))
const keyboardShortcuts = computed(() => {
  const enter = t('documents.mindmapHelp.enter'), escape = t('documents.mindmapHelp.escape'), space = t('documents.mindmapHelp.space')
  const shift = t('documents.mindmapHelp.shift'), modifier = $q.platform.is.mac ? 'Cmd' : 'Ctrl'
  const click = t('documents.mindmapHelp.click')
  const shiftEnter = `${shift}+${enter}`
  return [
    [t('documents.mindmapHelp.navigate'), '← ↑ ↓ →'],
    [t('documents.mindmapSelection.extend'), `${shift}+← ↑ ↓ → / ${shift}+${click}`],
    [t('documents.mindmapSelection.toggle'), `${modifier}+${click}`],
    [t('richEditor.find'), `${modifier}+F`],
    [t('richEditor.selectAll'), `${modifier}+A`],
    ...(!props.readonly ? [
      [t('richEditor.undo'), `${modifier}+Z`],
      [t('richEditor.redo'), `${modifier}+${shift}+Z / ${modifier}+Y`],
      [t('documents.mindmapHelp.edit'), enter],
      [t('documents.mindmap.icon'), 'F2'],
      [t('documents.mindmapHelp.checkboxField'), 'F3'],
      [t('documents.mindmapHelp.valueField'), 'F4'],
      [t('documents.mindmapHelp.navigateFromTitle'), 'Alt+← ↑ ↓ →'],
      [t('documents.mindmap.addChild'), `Tab / ${t('documents.mindmapHelp.insert')}`],
      [t('documents.mindmap.addSibling'), shiftEnter],
      [t('documents.mindmapHelp.reorder'), `${modifier}+↑ ↓`],
      [t('documents.mindmapHelp.reparent'), `${modifier}+← →`],
      [t('documents.mindmapHelp.toggleCheckbox'), space],
      [t('documents.mindmap.richContent'), `Alt+${enter}`],
      [t('documents.mindmap.editNote'), 'F6'],
      [t('documents.mindmap.link'), `${modifier}+K`],
      [t('richEditor.clipboard.cut'), `${modifier}+X`],
      [t('documents.mindmapClipboard.cancelCut'), escape],
      [t('richEditor.clipboard.copy'), `${modifier}+C`],
      [t('richEditor.clipboard.paste'), `${modifier}+V`],
      [t('documents.mindmapHelp.noteLineBreak'), shiftEnter],
      [t('documents.mindmap.remove'), `${t('documents.mindmapHelp.delete')} / Alt+${t('documents.mindmapHelp.delete')}`],
    ] : []),
    [t(props.readonly ? 'documents.mindmapHelp.fold' : 'documents.mindmapHelp.foldWithoutCheckbox'), space],
    [t('documents.mindmapHelp.leave'), `${escape}, Tab`],
    [t('documents.mindmapConnectors.shortcut'), 'Alt+J'],
    [t('documents.mindmapConnectors.follow'), '→'],
    [t('documents.mindmapConnectors.navigateLinks'), '↑ ↓'],
    [t('documents.mindmapConnectors.firstChild'), 'Alt+→'],
    [t('richEditor.help'), 'Alt+0'],
  ]
})
const hasBranches = computed(() => children.value.size > 1)

function nodeLabel(node: MindMapNode): string {
  return mindMapNodeLabel(node, props.documentTitle, t('documents.mindmap.untitled'))
}

function bodyMarkup(node: MindMapNode): string {
  const html = resourceBodies.value.get(node.id)?.html ?? mindMapParagraphHtml(node.title)
  return standaloneBody.value === node.id && node.link ? mindMapLinkHtml(node.link) + html : html
}

function depth(node: MindMapNode): number {
  let count = 0
  for (let parent = node.parent; parent !== null; parent = byId.value.get(parent)?.parent ?? null) count++
  return count
}

function subtree(roots: readonly MindMapNode[]): { ids: Set<string>; height: number } {
  const pending = roots.map(node => ({ node, level: 0 }))
  const ids = new Set<string>()
  let height = 0
  while (pending.length) {
    const current = pending.pop()!
    ids.add(current.node.id)
    height = Math.max(height, current.level)
    for (const child of children.value.get(current.node.id) ?? []) pending.push({ node: child, level: current.level + 1 })
  }
  return { ids, height }
}

function branchRoots(nodes: readonly MindMapNode[]): MindMapNode[] {
  const ids = new Set(nodes.map(node => node.id))
  return nodes.filter(node => {
    for (let parent = node.parent; parent !== null; parent = byId.value.get(parent)?.parent ?? null) {
      if (ids.has(parent)) return false
    }
    return true
  })
}

function branchesByIds(ids: readonly string[]): MindMapNode[] {
  const branches = ids.map(id => byId.value.get(id)).filter(node => node !== undefined)
  return branches.length === ids.length ? branchRoots(branches) : []
}

const selectedSubtree = computed(() => subtree(selectionRoots.value))
const dragBranches = computed(() => branchesByIds(dragged.value ?? []))
const dragSubtree = computed(() => subtree(dragBranches.value))
watch([dragBranches, () => props.readonly], ([branches, readonly]) => {
  if (dragged.value && (!branches.length || readonly)) stopDrag()
})
const cutBranches = computed(() => branchesByIds(branchClipboard.value?.mode === 'cut' ? branchClipboard.value.ids : []))
const cutSubtree = computed(() => subtree(cutBranches.value))
const cutPending = computed(() => branchClipboard.value?.mode === 'cut')
watch([cutBranches, () => props.readonly], ([branches, readonly]) => {
  if (!branches.length || readonly) endCut()
})

function canMoveTo(roots: readonly MindMapNode[], tree: ReturnType<typeof subtree>, parent: MindMapNode): boolean {
  return roots.length > 0 && !tree.ids.has(parent.id) && depth(parent) + 1 + tree.height <= maxDepth
}

const parents = computed(() => canMoveSelection.value ? (map.value?.nodes ?? [])
  .filter(node => canMoveTo(selectionRoots.value, selectedSubtree.value, node))
  .map(node => ({ value: node.id, label: nodeLabel(node) })) : [])
function canPasteBranches(parent: MindMapNode): boolean {
  const clip = branchClipboard.value
  if (!clip || clip.mode === 'inactiveCut' || !map.value || props.readonly) return false
  if (clip.mode === 'cut') return canMoveTo(cutBranches.value, cutSubtree.value, parent)
  return map.value.nodes.length + clip.nodes.length <= maxNodes && depth(parent) + 1 + clip.height <= maxDepth
    && connectors.value.length + clip.connectors.length <= maxConnectors
}

function commit(nodes: MindMapNode[], group?: string, links = map.value?.connectors): void {
  if (!props.readonly && map.value) history.record({ ...map.value, nodes, connectors: links?.length ? links : undefined }, group)
}

function restoreHistory(direction: 'undo' | 'redo'): void {
  if (props.readonly) return
  if (direction === 'undo' && cancelCut()) return
  commitDraft()
  const node = active.value
  if (!history.restore(direction)) return
  editingBody.value = undefined
  clearSelectionActions()
  oversizedBodies.value.clear()
  void nextTick(() => {
    const target = byId.value.get(node.id) ?? byId.value.get(node.parent ?? '') ?? root.value
    if (target) focusNode(target.id)
  })
}

function selectAllBranches(): void {
  focusNode(active.value.id, { kind: 'all' })
}

function openSearch(): void {
  commitDraft()
  searchOpen.value = true
  void nextTick(() => searchInput.value?.focus())
}

function closeSearch(): void {
  searchOpen.value = false
  searchIndex.value = -1
  focusNode(active.value.id)
}

function revealMatch({ target, range }: MindMapMatch, focusValue = false): void {
  const node = byId.value.get(target.id)
  if (!node) return
  unfoldAncestors(node)
  if (target.field === 'note') details.value.add(node.id)
  selectNode(node.id)
  void nextTick(() => {
    if (active.value.id !== node.id) return
    const input = focusValue && target.field === 'value' ? valueInput(node.id) : undefined
    if (input) {
      input.focus({ preventScroll: true })
      input.setSelectionRange(range.from, range.to)
    }
    reveal(input ?? branchElement(node.id)?.firstElementChild)
  })
}

function unfoldAncestors(node: MindMapNode): void {
  for (let parent = node.parent; parent; parent = byId.value.get(parent)?.parent ?? null) folded.value.delete(parent)
}

function openConnectors(id: string, target?: string): void {
  if (!byId.value.has(id)) return
  connectorTarget.value = target
  connectorLabel.value = ''
  connectorEdit.value = undefined
  connectorNodeId.value = id
}

function editConnector(connector: MindMapConnector): void {
  openConnectors(connector.source, connector.target)
  connectorEdit.value = connector
  connectorLabel.value = connector.label
}

function openConnectorByKey(key: string): void {
  const connector = connectors.value.find(link => connectorKey(link) === key)
  if (!connector) return
  if (props.readonly) openConnectors(connector.source)
  else editConnector(connector)
}

function openSelectedConnectors(): void {
  const [first, second] = selection.value
  if (!props.readonly && !leavingTree.value && selection.value.length === 2 && first && second
    && connectors.value.length < maxConnectors && !connectorsByNode.value.get(first.id)?.some(link => link.other.id === second.id)) {
    const [source, target] = active.value.id === first.id ? [second, first] : [first, second]
    openConnectors(source.id, target.id)
  } else openConnectors(active.value.id)
}

function saveConnector(): void {
  const source = connectorNode.value?.id, target = connectorTarget.value
  if (!source || !target || !map.value || !canSaveConnector.value) return
  const connector = { source, target, label: connectorLabel.value.trim() }
  const links = connectorEdit.value
    ? connectors.value.map(link => link === formConnector.value ? connector : link)
    : [...connectors.value, connector]
  commit(map.value.nodes, undefined, links)
  openConnectors(source)
}

function jumpToConnector(id: string): void {
  const node = byId.value.get(id)
  if (!node) return
  connectorNavigation.value = undefined
  connectorNodeId.value = undefined
  unfoldAncestors(node)
  focusNode(id)
}

function removeConnector(): void {
  const connector = connectorRemoval.value
  connectorRemoval.value = undefined
  if (!connector || !map.value) return
  commit(map.value.nodes, undefined, connectors.value.filter(link =>
    link.source !== connector.source || link.target !== connector.target || link.label !== connector.label))
  if (connectorEdit.value === connector) openConnectors(connector.source)
}

function findNext(): void {
  if (!matches.value.length) return
  searchIndex.value = (searchIndex.value + 1) % matches.value.length
  revealMatch(matches.value[searchIndex.value]!, true)
}

function replaceResults(all: boolean): void {
  const current = map.value
  if (!current || props.readonly || !matches.value.length) return
  // A separate parse keeps the cached search results intact if validation fails.
  const fresh = searchMindMap(orderedNodes.value, query.value, matchCase.value, wholeWords.value)
  const index = Math.max(0, searchIndex.value)
  const affected = all ? fresh : fresh.slice(index, index + 1)
  const nodes = replaceMindMapMatches(current.nodes, affected, replacement.value)
  if (!parseMindMap(JSON.stringify({ ...current, nodes }))) {
    $q.notify({ type: 'negative', message: t('documents.mindmapEditing.replaceTooLarge') })
    return
  }
  commit(nodes)
  if (!all && affected[0]) revealMatch(affected[0])
}

function clearSelectionActions(): void {
  pendingRemove.value = null
  changingParent.value = null
  inspectedBody.value = undefined
  standaloneBody.value = undefined
  pendingReference.value = undefined
  previewSelection.value = undefined
}

function branchElement(id: string): HTMLElement | null | undefined {
  return canvas.value?.querySelector<HTMLElement>(`[data-mindmap-node="${id}"]`)
}

function titleElement(id: string): HTMLElement | null | undefined {
  return branchElement(id)?.querySelector<HTMLElement>(':scope > .mindmap-node > .mindmap-node-line > .mindmap-title')
}

function valueInput(id: string): HTMLInputElement | null | undefined {
  return branchElement(id)?.querySelector<HTMLInputElement>(':scope > .mindmap-node > .mindmap-node-line > .mindmap-value-input')
}

function selectNode(id: string, selection?: BranchSelection): void {
  if (active.value.id !== id) {
    commitDraft()
    clearSelectionActions()
    pendingBody.value = undefined
    editingBody.value = undefined
  }
  branchSelection.value = selection
  leavingTree.value = false
  selected.value = id
}

function focusNode(id: string, selection?: BranchSelection): void {
  selectNode(id, selection)
  void nextTick(() => {
    if (active.value.id !== id || leavingTree.value) return
    const node = branchElement(id)
    const target = (!props.readonly && !selection ? valueInput(id) : undefined) ?? node
    target?.focus({ preventScroll: true })
    reveal(target === node ? node?.firstElementChild?.firstElementChild : target)
  })
}

function revealTitle(id: string): void { reveal(titleElement(id)?.parentElement) }

function onCanvasPointerDown(event: PointerEvent): void {
  selectedOnPointerDown = visibleSelection.value.size === 1 && visibleSelection.value.has(selected.value) ? selected.value : ''
  pointerDown(event)
}

function wasSelected(event: MouseEvent, id: string): boolean {
  return event.detail ? selectedOnPointerDown === id : selectedIds.value.size === 1 && selectedIds.value.has(id)
}

function modifiedClickBranch(event: MouseEvent): HTMLElement | null | undefined {
  const target = event.target
  if (event.button !== 0 || !(event.shiftKey || event.ctrlKey || event.metaKey) || !(target instanceof Element)
    || target.closest('.mindmap-canvas') !== canvas.value || !target.closest('.mindmap-node')
    || target.closest('button, input, textarea, select, [role="button"], [role="checkbox"], [contenteditable]:not([contenteditable="false"]), .galaris-image-resize, [data-document-player], [data-resource-mode="embed"] > .galaris-resource-embed')) return
  // Ctrl/Cmd+click on the link itself still opens the referenced object.
  if (!event.shiftKey && target.closest('a[href]')) return
  return target.closest<HTMLElement>('[data-mindmap-node]')
}

function selectWithModifiers(event: MouseEvent): void {
  const id = modifiedClickBranch(event)?.dataset.mindmapNode
  if (!id || !byId.value.has(id)) return
  event.preventDefault()
  event.stopPropagation()
  if (active.value.id === id) {
    commitDraft()
    clearSelectionActions()
    pendingBody.value = undefined
    editingBody.value = undefined
  }
  if (event.shiftKey) {
    focusNode(id, { kind: 'range', anchor: selectionAnchor.value ?? active.value.id })
  } else {
    const ids = new Set(selectedIds.value)
    if (!ids.delete(id)) ids.add(id)
    focusNode(id, { kind: 'nodes', anchor: id, ids })
  }
}

function selectTitle(event: MouseEvent, id: string): void {
  if (byId.value.get(id)?.value == null && wasSelected(event, id) && !props.readonly) focusTitle(id)
  else focusNode(id)
}

function editValueNodeTitle(event: MouseEvent, node: MindMapNode): void {
  if (node.value == null || props.readonly || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  focusTitle(node.id)
}

function selectBody(event: MouseEvent, id: string): void {
  if (event.defaultPrevented || !(event.target instanceof Element)
    || event.target.closest('a, button, input, video, audio, iframe, [data-resource-mode="embed"] > .galaris-resource-embed')) return
  if (wasSelected(event, id) && !props.readonly) openBody(id)
  else focusNode(id)
}

function focusTitle(id: string, text = ''): void {
  if (props.readonly) return
  const node = byId.value.get(id)
  if (node?.body_html && node.value == null) { openBody(id, text); return }
  selectNode(id)
  if (editingTitle.value?.id !== id) editingTitle.value = { id, initial: node?.title ?? '' }
  void nextTick(() => {
    if (props.readonly || active.value.id !== id || editingTitle.value?.id !== id) return
    const title = titleElement(id)
    if (!title) return
    title.focus({ preventScroll: true })
    if (text) title.append(text)
    window.getSelection()?.collapse(title, title.childNodes.length)
  })
}

function finishTitle(id: string): void {
  const draft = editingTitle.value
  if (draft?.id !== id) return
  const title = titleElement(id)
  const node = byId.value.get(id)
  editingTitle.value = undefined
  if (!title || !node || !map.value || props.readonly) return
  const text = title.innerText
  if (text === draft.initial) return
  const value = Array.from(text).slice(0, titleLength).join('')
  if (value !== node.title) commit(map.value.nodes.map(candidate => candidate.id === id ? { ...candidate, title: value } : candidate))
}

function onTitleKeydown(event: KeyboardEvent, id: string): void {
  const node = byId.value.get(id)
  if (event.isComposing || !node) return
  const { key, altKey, ctrlKey, metaKey, shiftKey } = event
  if (altKey && !ctrlKey && !metaKey && key.startsWith('Arrow')) {
    navigateBranches(event, node)
    return
  }
  if (onNodeShortcut(event, node)) return
  if (onMoveShortcut(event)) return
  if (altKey && !ctrlKey && !metaKey && (key === 'Delete' || key === '0' || event.code === 'Digit0')) {
    if (key === 'Delete' && canMoveSelection.value) {
      event.preventDefault()
      event.stopPropagation()
      finishTitle(id)
      focusNode(id)
      void nextTick(confirmRemove)
      return
    }
    onTreeKeydown(event, node)
    return
  }
  const field = (ctrlKey || metaKey) && key.toLowerCase() === 'k' ? 'link' : undefined
  if (field) { event.preventDefault(); beginEdit(id, field); return }
  const addChild = !altKey && !ctrlKey && !metaKey && !shiftKey && (key === 'Tab' || key === 'Insert') && canAdd(node)
  if (!addChild && key !== 'Enter' && key !== 'Escape') return
  event.preventDefault()
  event.stopPropagation()
  if (key === 'Escape') editingTitle.value = undefined
  else finishTitle(id)
  if (addChild) void nextTick(() => addBranch(byId.value.get(id)))
  else if (key === 'Enter' && altKey) void nextTick(() => openBody(id))
  else focusNode(id)
}

function openIconPicker(): void {
  iconId.value = active.value.id
  iconOpen.value = true
}

function onNodeShortcut(event: KeyboardEvent, node: MindMapNode): boolean {
  const { key, altKey, ctrlKey, metaKey, shiftKey } = event
  if (!event.defaultPrevented && !event.isComposing && altKey && !ctrlKey && !metaKey && !shiftKey && key.toLowerCase() === 'j') {
    if (props.readonly && !connectorsByNode.value.has(node.id)) return false
    event.preventDefault()
    event.stopPropagation()
    if (!event.repeat) {
      if (!props.readonly && selection.value.length === 2) openSelectedConnectors()
      else if (!followConnector(node.id)) openConnectors(node.id)
    }
    return true
  }
  if (props.readonly || event.defaultPrevented || event.isComposing || altKey || ctrlKey || metaKey || shiftKey
    || !['F2', 'F3', 'F4', 'F6'].includes(key) || (key === 'F2' && node.body_html && node.value == null)) return false
  event.preventDefault()
  event.stopPropagation()
  if (event.repeat) return true
  const editingLabel = editingTitle.value?.id === node.id
  if (editingLabel) finishTitle(node.id)
  if (key === 'F2') {
    if (editingLabel) {
      focusNode(node.id)
      void nextTick(openIconPicker)
    } else openIconPicker()
  } else if (key === 'F3') {
    setSelectionCheckboxes(node.checked == null)
    if (editingLabel) focusNode(node.id)
  } else if (key === 'F4') setSelectionValues(node.value == null)
  else beginEdit(node.id, 'note')
  return true
}

async function saveIcon(icon: string | null): Promise<boolean> {
  const id = iconNode.value?.id
  if (!id || !map.value || props.readonly) return false
  commit(map.value.nodes.map(node => node.id === id ? { ...node, icon: icon ?? '' } : node))
  return true
}

function openBody(id: string, text = ''): void {
  const node = byId.value.get(id)
  if (props.readonly || !map.value || !node) return
  selectNode(id)
  if (activeBody.value === id && bodyEditor.value?.editor) {
    activateBody(text)
    return
  }
  editingBody.value = id
  const pending = pendingBody.value
  pendingBody.value = { id, text: pending?.id === id ? pending.text + text : text }
  if (!node.body_html) {
    const body_html = mindMapParagraphHtml(node.title)
    commit(map.value.nodes.map(candidate => candidate.id === id ? { ...candidate, body_html } : candidate), id)
  }
}

function closeBody(): void {
  const id = activeSurface.value
  if (!id) return
  editingBody.value = undefined
  pendingBody.value = undefined
  clearSelectionActions()
  focusNode(id)
}

function onBodyEscape(event: KeyboardEvent): void {
  if (event.defaultPrevented || event.isComposing || !activeSurface.value) return
  event.preventDefault()
  event.stopPropagation()
  closeBody()
}

function activateBody(text: string): void {
  const editor = bodyEditor.value?.editor
  if (!editor || editor.isDestroyed || !editor.isEditable) return
  reveal(editor.view.dom)
  if (!text) {
    editor.commands.focus('end', { scrollIntoView: false })
    return
  }
  const { doc } = editor.state
  const content = { type: 'text', text }
  // Insert after a terminal object instead of typing over its node selection.
  if (doc.lastChild?.isTextblock && !doc.lastChild.isAtom) editor.commands.insertContentAt(doc.content.size - 1, content)
  else editor.commands.insertContentAt(doc.content.size, { type: 'paragraph', content: [content] })
  editor.view.focus()
}

watch([() => bodyEditor.value?.editor, pendingBody], ([editor, pending]) => {
  if (!editor || !pending || pending.id !== activeBody.value) return
  pendingBody.value = undefined
  activateBody(pending.text)
}, { flush: 'post' })

function typedCharacter(event: KeyboardEvent): string | undefined {
  if (event.defaultPrevented || event.isComposing || event.metaKey) return
  if ((event.ctrlKey || event.altKey) && !event.getModifierState('AltGraph')) return
  return [...event.key].length === 1 && !/\p{C}/u.test(event.key) ? event.key : undefined
}

function typeInInspectedBody(event: KeyboardEvent, id: string): void {
  if (props.readonly || activeSurface.value !== id || activeBody.value || !(event.target instanceof HTMLElement)
    || !event.target.hasAttribute('data-editor-surface')) return
  const text = typedCharacter(event)
  if (!text) return
  event.preventDefault()
  event.stopPropagation()
  const node = byId.value.get(id)
  if (text === ' ' && node?.checked != null) { toggleCheckboxes(node); return }
  openBody(id, text)
}

function appendChildren(parentId: string, branches: readonly Pick<MindMapNode, 'title' | 'body_html'>[]): boolean {
  const parent = byId.value.get(parentId)
  if (props.readonly || disposed || !map.value || !canAdd(parent) || !branches.length
    || map.value.nodes.length + branches.length > maxNodes || branches.some(branch => Array.from(branch.body_html ?? '').length > 128_000)) {
    $q.notify({ type: 'warning', message: t('richEditor.resources.failed') })
    return false
  }
  const nodes = branches.map(branch => ({ ...branch, title: Array.from(branch.title).slice(0, titleLength).join(''), id: crypto.randomUUID(), parent: parentId }))
  folded.value.delete(parentId)
  commit([...map.value.nodes, ...nodes])
  return true
}

function insertResourceBranches(parentId: string, markup: string): void {
  if (!markup || props.readonly || disposed) return
  const blocks = new DOMParser().parseFromString(markup, 'text/html').body.children
  const nodes = Array.from(blocks).flatMap(block => {
    const link = block.matches('a[href]') ? block : block.querySelector('a[href]')
    const label = link?.textContent?.trim() || block.querySelector('img')?.getAttribute('alt') || link?.getAttribute('href')
    return label && link ? [{ title: label, body_html: block.outerHTML }] : []
  })
  if (nodes.length !== blocks.length) {
    $q.notify({ type: 'warning', message: t('richEditor.resources.failed') })
    return
  }
  appendChildren(parentId, nodes)
}

function openLinkDialog(parent: MindMapNode): void {
  if (props.readonly || !canAdd(parent)) return
  linkDraft.value = { parent: parent.id, url: '', title: '' }
  linkDialogOpen.value = true
}

function linkChild(uri: string, title: string): Pick<MindMapNode, 'title' | 'body_html'> {
  return { title, body_html: `<p>${resourceLinkElement(uri, title).outerHTML}</p>` }
}

function insertLinkChild(): void {
  const uri = linkUri.value, { parent, title } = linkDraft.value
  if (uri && appendChildren(parent, [linkChild(uri, title.trim() || uri)])) linkDialogOpen.value = false
}

function insertResource(markup: string): void {
  if (props.readonly) return
  if (activeBody.value && bodyEditor.value?.editor) bodyEditor.value.insertResource(markup)
  else insertResourceBranches(active.value.id, markup)
}

async function chooseInternalResources(): Promise<void> {
  if (props.readonly) return
  if (!canAdd(active.value) || !props.pickResources) return
  const parentId = active.value.id
  try { insertResourceBranches(parentId, await props.pickResources()) }
  catch { if (!disposed) $q.notify({ type: 'negative', message: t('richEditor.resources.failed') }) }
}

function chooseFiles(): void {
  if (props.readonly) return
  if (!canAdd(active.value)) return
  fileParent = active.value.id
  fileInput.value?.click()
}

function filesChosen(event: Event): void {
  if (!(event.target instanceof HTMLInputElement)) return
  const files = Array.from(event.target.files ?? [])
  event.target.value = ''
  if (fileParent) void uploadResourceBranches(fileParent, files)
  fileParent = undefined
}

async function uploadResourceBranches(parentId: string, sources: readonly (File | { uri: string; name: string })[]): Promise<void> {
  const upload = props.uploadFile ?? props.uploadImage
  if (!sources.length || uploading.value || props.readonly || !map.value) return
  if (!canAdd(byId.value.get(parentId)) || map.value.nodes.length + sources.length > maxNodes) {
    $q.notify({ type: 'warning', message: t('richEditor.resources.failed') })
    return
  }
  const request = new AbortController()
  uploadRequest = request
  uploading.value = true
  const blocks: string[] = []
  try {
    for (const source of sources) {
      if (request.signal.aborted || props.readonly || !byId.value.has(parentId)) break
      try {
        if (source instanceof File && upload) {
          const uri = await upload(source, request.signal, () => {})
          blocks.push(documentResourceHtml({ uri, name: source.name, size: source.size, mediaType: source.type }))
        } else if (!(source instanceof File) && props.importImage) {
          const uri = await props.importImage(source.uri, request.signal)
          blocks.push(documentResourceHtml({ uri, name: source.name, size: 0, mediaType: 'image/png' }))
        }
      } catch {
        if (!request.signal.aborted) $q.notify({ type: 'negative', message: t('richEditor.resources.uploadFailed', { name: source.name }) })
      }
    }
    if (!request.signal.aborted) insertResourceBranches(parentId, blocks.join(''))
  } finally {
    uploadRequest = undefined
    uploading.value = false
  }
}

function resourceDropParent(event: DragEvent): MindMapNode | undefined {
  if (props.readonly || dragged.value || event.defaultPrevented || !(event.target instanceof Element)
    || event.target.closest('.mindmap-canvas') !== canvas.value || event.target.closest('[data-editor-surface]')) return
  const id = event.target.closest<HTMLElement>('[data-mindmap-node]')?.dataset.mindmapNode
  return id ? byId.value.get(id) : active.value
}

function allowResourceDrop(event: DragEvent): void {
  const parent = resourceDropParent(event), data = event.dataTransfer
  if (!data || !canAdd(parent)) return
  const accepts = data.types.includes('Files') ? Boolean(props.uploadFile ?? props.uploadImage) && !uploading.value
    : data.types.some(type => type === 'text/html' || type === 'text/uri-list' || type === 'text/plain')
  if (!accepts) return
  event.preventDefault()
  data.dropEffect = 'copy'
  markDropTarget(parent.id, 'inside')
}

function leaveCanvas(event: DragEvent): void {
  if (!(event.relatedTarget instanceof Node && canvas.value?.contains(event.relatedTarget))) dropTarget.value = undefined
}

function dropResources(event: DragEvent): void {
  const parent = resourceDropParent(event), data = event.dataTransfer
  dropTarget.value = undefined
  if (!data || !canAdd(parent)) return
  const files = Array.from(data.files)
  if (files.length) {
    event.preventDefault()
    if (props.uploadFile ?? props.uploadImage) void uploadResourceBranches(parent.id, files)
    return
  }
  const { links, images } = mindMapDroppedResources(data)
  if (images.length && props.importImage) {
    event.preventDefault()
    void uploadResourceBranches(parent.id, images)
    return
  }
  if (!links.length) return
  event.preventDefault()
  const markup = links.map(({ uri, name }) => {
    const attachment = props.attachments?.find(value => value.uri === uri)
    if (attachment) return documentResourceHtml(attachment)
    const mode = richLinkDefaultMode(uri, 'mindmap')
    return mode === 'link' ? resourceLinkElement(uri, name).outerHTML : resourceBlock(uri, name, mode).outerHTML
  }).join('')
  insertResourceBranches(parent.id, markup)
}

function selectReference(event: MouseEvent, id: string): void {
  const target = event.target
  if (event.ctrlKey || event.metaKey || !(target instanceof Element) || !target.closest('.rich-content-reader')
    || target.closest('button, input, select, textarea, .galaris-image-resize, [data-document-player], [data-resource-mode="embed"] > .galaris-resource-embed')) return
  const reader = target.closest('.rich-content-reader')!
  const card = target.closest<HTMLElement>('blockquote.galaris-link-card')
  const image = target.closest('img') ?? target.closest('figure.image, .image-inline')?.querySelector('img')
  const link = target.closest('a[data-rich-reference]')
  const table = target.closest('table')
  const element = card?.querySelector('a') ?? image ?? link ?? table
  if (!element) return
  const kind = card ? 'card' : image ? 'image' : link ? 'link' : 'table'
  const uri = kind === 'table' ? '' : element.getAttribute('data-rich-reference') ?? element.getAttribute('href') ?? ''
  if (props.readonly) {
    if (documentUriFromLink(uri, window.location.origin)) {
      event.preventDefault()
      event.stopPropagation()
      focusNode(id)
    }
    return
  }
  const selector = kind === 'image' ? 'img' : kind === 'table' ? 'table' : 'a'
  const matches = [...reader.querySelectorAll(selector)].filter(candidate =>
    (kind !== 'card' || Boolean(candidate.closest('blockquote.galaris-link-card')))
    && (kind !== 'link' || !candidate.closest('blockquote.galaris-link-card, figure.image, .image-inline'))
    && (!uri || (candidate.getAttribute('data-rich-reference') ?? candidate.getAttribute('href')) === uri))
  event.preventDefault()
  event.stopPropagation()
  selectNode(id)
  if (reader.closest('.mindmap-standalone-link')) standaloneBody.value = id
  else if (kind !== 'table') previewSelection.value = {
    id, card, image: card ? card.matches('.image') ? card.querySelector('img') : undefined : image,
  }
  inspectedBody.value = id
  pendingReference.value = { id, uri, index: Math.max(0, matches.findIndex(candidate => candidate === element)), kind }
}

function registerPreviewActions(card: HTMLElement, actions: readonly DocumentReferenceAction[]): void {
  if (actions.length) previewActions.set(card, actions)
  else previewActions.delete(card)
}

function focusWithinPreview(target: Node): boolean {
  return target === pressedBranch || target instanceof Element
    && Boolean(target.closest('.mindmap-details .rich-content-reader') && canvas.value?.contains(target))
}

function preserveBranchFocus(event: MouseEvent): void {
  const target = event.target
  if (event.button !== 0 || !(target instanceof Element)) return
  const branch = target.closest<HTMLElement>('[data-mindmap-node]')
  const draggingSelection = selection.value.length > 1 && selectedIds.value.has(branch?.dataset.mindmapNode ?? '')
    && target.closest('[draggable="true"]')
  if (!draggingSelection && !focusWithinPreview(target) && !modifiedClickBranch(event)) return
  pressedBranch = branch
  // A mouse press can focus the tree item before its click or dragstart is delivered.
  requestAnimationFrame(() => { if (pressedBranch === branch) pressedBranch = null })
}

watch(inspectedPreview, (selection, _, cleanup) => {
  const image = selection?.image
  if (!image) return
  const existingFrame = selection.card ?? image.closest<HTMLElement>('figure.image, span.image-inline')
  const frame = existingFrame ?? image.ownerDocument.createElement('span')
  if (!existingFrame) {
    frame.className = 'image-inline'
    image.before(frame)
    frame.append(image)
  }
  frame.classList.add('mindmap-selected-image')
  const dispose = mountImageResize(frame, () => !props.readonly, () => image,
    width => bodyEditor.value?.resizeSelectedImage(width), true)
  cleanup(() => {
    dispose()
    frame.classList.remove('mindmap-selected-image')
    if (!existingFrame) frame.replaceWith(image)
  })
}, { flush: 'post' })

watch([() => bodyEditor.value?.editor, pendingReference], ([editor, selection]) => {
  if (!editor || !selection || selection.id !== activeSurface.value) return
  pendingReference.value = undefined
  bodyEditor.value?.selectResource(selection.uri, selection.index, selection.kind)
}, { flush: 'post' })

watch(() => props.readonly, value => { if (value) { uploadRequest?.abort(); history.clear() } })
watch(() => props.resourceAgentId, () => { graphicRequest?.abort(); shareOpen.value = false; history.clear() })
onBeforeUnmount(() => { disposed = true; uploadRequest?.abort(); graphicRequest?.abort() })

function updateBody(id: string, html: string): void {
  if (!map.value || props.readonly || activeSurface.value !== id) return
  previewSelection.value = undefined
  if (Array.from(html).length > 128_000) {
    oversizedBodies.value.set(id, html)
    return
  }
  oversizedBodies.value.delete(id)
  commit(map.value.nodes.map(node => node.id === id ? { ...node,
    ...(standaloneBody.value === id ? { link: '' } : {}), body_html: html || '<p></p>',
  } : node), activeBody.value === id ? id : undefined)
  if (standaloneBody.value === id) standaloneBody.value = undefined
}

function resizeNodeEmbed(id: string, index: number, uri: string, size: DocumentEmbedSize): void {
  if (!map.value || props.readonly) return
  const node = byId.value.get(id)
  if (!node?.body_html) return
  const body = new DOMParser().parseFromString(node.body_html, 'text/html').body
  const card = documentReferenceCards(body)[index]
  if (!card || referenceMode(card) !== 'embed' || referenceUri(card) !== uri) return
  const previous = card.dataset.resourceSize
  writeDocumentEmbedSize(card, size)
  const html = body.innerHTML
  if (card.dataset.resourceSize === previous || Array.from(html).length > 128_000) return
  if (activeSurface.value === id) {
    const hostHtml = standaloneBody.value === id && node.link ? mindMapLinkHtml(node.link) + html : html
    bodyEditor.value?.syncReferenceSize(index, uri, size, hostHtml)
  }
  commit(map.value.nodes.map(branch => branch.id === id ? { ...branch, body_html: html } : branch))
}

function onTreeFocus(event: FocusEvent): void {
  if (event.target === pressedBranch) return
  const id = event.target instanceof HTMLElement ? event.target.dataset.mindmapNode : undefined
  if (id && (selected.value !== id || leavingTree.value)) selectNode(id)
  if (id && !props.readonly && !branchSelection.value) valueInput(id)?.focus({ preventScroll: true })
}

function onMapFocus(event: FocusEvent): void {
  const target = event.type === 'focusin' ? event.target : event.relatedTarget
  mapFocused.value = target instanceof Element && target.closest('.mindmap') === event.currentTarget
}

function selectValue(id: string): void {
  if (active.value.id !== id || leavingTree.value || branchSelection.value) selectNode(id)
}

function setSelectionValues(add: boolean): void {
  if (!map.value || props.readonly || pendingValueRemoval.value) return
  const nodes = selection.value
  const ids = new Set(nodes.map(node => node.id))
  if (!add && nodes.some(node => node.value)) {
    pendingValueRemoval.value = ids
    return
  }
  applyValueFields(ids, add)
}

function confirmValueRemoval(): void {
  const ids = pendingValueRemoval.value
  pendingValueRemoval.value = undefined
  if (ids) applyValueFields(ids, false)
}

function applyValueFields(ids: ReadonlySet<string>, add: boolean): void {
  if (!map.value || props.readonly) return
  const id = active.value.id
  const currentSelection = branchSelection.value
  commit(map.value.nodes.map(node => {
    if (!ids.has(node.id) || add === (node.value != null)) return node
    const updated = { ...node }
    if (add) updated.value = ''
    else delete updated.value
    return updated
  }))
  focusNode(id, currentSelection)
}

function updateNodeValue(event: Event, id: string): void {
  if (event instanceof InputEvent && event.isComposing) return
  if (event.target instanceof HTMLInputElement) setNodeValue(id, event.target.value)
}

function setNodeValue(id: string, value: string): void {
  const node = byId.value.get(id)
  if (!map.value || props.readonly || node?.value == null || node.value === value) return
  commit(map.value.nodes.map(candidate => candidate.id === id ? { ...candidate, value } : candidate), `value:${id}`)
}

async function copyNodeValue(value: string, message = 'documents.mindmapValue.copied'): Promise<void> {
  const previous = branchClipboard.value
  try {
    await copyToClipboard(value)
    if (branchClipboard.value === previous) branchClipboard.value = undefined
    $q.notify({ type: 'positive', message: t(message) })
  } catch {
    $q.notify({ type: 'negative', message: t('richEditor.clipboard.failed') })
  }
}

function copySelectedValues(asTable: boolean): void {
  function tableCell(text: string): string {
    const value = /^[\s\u0000-\u001f]*[=+@-]/u.test(text) ? "'" + text : text
    return /["\t\r\n]/u.test(value) ? `"${value.replaceAll('"', '""')}"` : value
  }
  const rows = selectedValues.value
  if (!rows.length) return
  const lines = rows.map(({ title, value }) => asTable ? [title, value].map(tableCell).join('\t') : value)
  void copyNodeValue(lines.join('\n'), 'documents.mindmapValue.selectionCopied')
}

function onValueKeydown(event: KeyboardEvent, node: MindMapNode): void {
  if (event.isComposing || event.defaultPrevented) return
  if (onNodeShortcut(event, node)) return
  if (onMoveShortcut(event)) return
  const { key, altKey, ctrlKey, metaKey, shiftKey, target } = event
  const vertical = key === 'ArrowUp' || key === 'ArrowDown'
  const atTextEdge = !shiftKey && target instanceof HTMLInputElement
    && target.selectionStart === target.selectionEnd
    && ((key === 'ArrowLeft' && target.selectionStart === 0)
      || (key === 'ArrowRight' && target.selectionEnd === target.value.length))
  if (!ctrlKey && !metaKey && (vertical || atTextEdge || (altKey && key.startsWith('Arrow')))) {
    navigateBranches(event, node)
    return
  }
  if ((ctrlKey || metaKey) && !altKey && !shiftKey && key.toLowerCase() === 'f') {
    onTreeKeydown(event, node)
    return
  }
  if (props.readonly) return
  if (key === 'Enter' || key === 'Escape' || key === 'Insert' || key === 'F3'
    || (altKey && (key === 'Delete' || key === '0' || event.code === 'Digit0'))
    || ((ctrlKey || metaKey) && ['k', 'y', 'z'].includes(key.toLowerCase()))) {
    onTreeKeydown(event, node)
  }
}

function canAdd(parent?: MindMapNode): parent is MindMapNode {
  return !!parent && !!map.value && map.value.nodes.length < maxNodes && depth(parent) < maxDepth
}

function setCheckbox(id: string, checked: boolean): void {
  const node = byId.value.get(id)
  if (node) updateCheckboxes([node], checked)
}

function setSelectionCheckboxes(add: boolean): void {
  const nodes = selection.value.filter(node => add ? node.checked == null : node.checked != null)
  updateCheckboxes(nodes, add ? false : undefined)
}

function toggleCheckboxes(node: MindMapNode): void {
  const nodes = selectionIds.value.has(node.id) ? selection.value.filter(candidate => candidate.checked != null) : [node]
  updateCheckboxes(nodes, !node.checked)
}

function updateCheckboxes(nodes: readonly MindMapNode[], checked: boolean | undefined): void {
  if (!map.value || props.readonly || !nodes.length) return
  const ids = new Set(nodes.map(node => node.id))
  commit(map.value.nodes.map(node => {
    if (!ids.has(node.id)) return node
    const updated = { ...node }
    if (checked === undefined) delete updated.checked
    else updated.checked = checked
    return updated
  }))
}

function addBranch(parent?: MindMapNode, after?: MindMapNode): void {
  if (props.readonly || !canAdd(parent) || !map.value) return
  const id = crypto.randomUUID()
  const nodes = map.value.nodes.slice()
  const index = after ? nodes.findIndex(node => node.id === after.id) + 1 : nodes.length
  nodes.splice(index, 0, { id, parent: parent.id, title: '', ...(after?.checked != null ? { checked: false } : {}) })
  folded.value.delete(parent.id)
  commit(nodes)
  focusTitle(id)
}

function addSibling(): void {
  const node = active.value
  if (node.parent !== null) addBranch(byId.value.get(node.parent), node)
}

function beginEdit(id: string, field: Field): void {
  if (props.readonly) return
  if (editing.value?.id === id && editing.value.field === field) return
  commitDraft()
  clearSelectionActions()
  selectNode(id)
  editing.value = { id, field, value: byId.value.get(id)?.[field] ?? '' }
  void nextTick(() => {
    if (editing.value?.id !== id || editing.value.field !== field) return
    const input = branchElement(id)?.querySelector<HTMLInputElement | HTMLTextAreaElement>('.mindmap-detail-input :is(input, textarea)')
    if (!input) return
    input.focus()
    input.setSelectionRange(input.value.length, input.value.length)
  })
}

function updateDraft(value: string | number | null): void {
  if (editing.value) editing.value.value = String(value ?? '')
}

function commitDraft(): void {
  finishTitle(active.value.id)
  commitDetailsDraft()
}

function commitDetailsDraft(): void {
  const draft = editing.value
  editing.value = null
  if (!draft || !map.value || (byId.value.get(draft.id)?.[draft.field] ?? '') === draft.value) return
  commit(map.value.nodes.map(node => node.id === draft.id ? { ...node, [draft.field]: draft.value } : node))
}

function onEditKeydown(event: KeyboardEvent): void {
  if (event.isComposing || !editing.value) return
  const { id, field } = editing.value
  if (event.key === 'Escape') editing.value = null
  else if (event.key === 'Enter' && !(field === 'note' && event.shiftKey)) {
    commitDraft()
    details.value.add(id)
  } else return
  event.preventDefault()
  event.stopPropagation()
  focusNode(id)
}

function toggleFold(id: string): void {
  if (!children.value.get(id)?.length) return
  if (folded.value.delete(id)) {
    focusNode(id)
    return
  }
  folded.value.add(id)
  focusNode(id)
}

function collapseAll(): void {
  folded.value = new Set([...children.value.keys()].filter((id): id is string => id !== null && id !== root.value?.id))
  if (root.value) focusNode(root.value.id)
}

function detailsOpen(node: MindMapNode): boolean {
  return Boolean(node.body_html) || details.value.has(node.id)
}

function toggleDetails(id: string): void {
  const node = byId.value.get(id)
  if (!node || node.body_html) return
  if (!details.value.delete(id)) details.value.add(id)
  focusNode(id)
}

function chooseParent(parent: string): void {
  if (!parents.value.some(option => option.value === parent)) return
  if (selectionRoots.value.every(node => node.parent === parent)) { changingParent.value = null; return }
  moveBranches(selectionRoots.value, parent)
}

function focusBranches(nodes: readonly MindMapNode[]): void {
  const last = nodes.at(-1)
  if (last) focusNode(last.id, nodes.length > 1 ? { kind: 'nodes', anchor: nodes[0]!.id, ids: new Set(nodes.map(node => node.id)) } : undefined)
}

function branchDestination(roots: readonly MindMapNode[], tree: ReturnType<typeof subtree>, target: MindMapNode, placement: BranchPlacement): MindMapNode | undefined {
  if (tree.ids.has(target.id)) return
  const parent = placement === 'inside' ? target : target.parent === null ? undefined : byId.value.get(target.parent)
  if (parent && canMoveTo(roots, tree, parent)) return parent
}

function moveBranches(roots: readonly MindMapNode[], targetId: string, placement: BranchPlacement = 'inside'): boolean {
  const target = byId.value.get(targetId)
  if (props.readonly || !map.value || !target || roots.some(node => node.parent === null)) return false
  const parent = branchDestination(roots, subtree(roots), target, placement)
  if (!parent) return false
  const ids = new Set(roots.map(node => node.id))
  const nodes = map.value.nodes.filter(node => !ids.has(node.id))
  const index = placement === 'inside' ? nodes.length : nodes.findIndex(node => node.id === targetId) + (placement === 'after' ? 1 : 0)
  nodes.splice(index, 0, ...roots.map(node => ({ ...node, parent: parent.id })))
  const previous = children.value.get(parent.id) ?? []
  const next = nodes.filter(node => node.parent === parent.id)
  if (next.length !== previous.length || next.some((node, index) => node.id !== previous[index]?.id)) commit(nodes)
  folded.value.delete(parent.id)
  clearSelectionActions()
  focusBranches(roots)
  return true
}

function reorderNeighbor(direction: -1 | 1): MindMapNode | undefined {
  const roots = selectionRoots.value, edge = direction < 0 ? roots[0] : roots.at(-1)
  if (!edge || edge.parent === null || roots.some(node => node.parent !== edge.parent)) return undefined
  const siblings = children.value.get(edge.parent) ?? []
  return siblings[siblings.findIndex(node => node.id === edge.id) + direction]
}

function reorder(direction: -1 | 1): void {
  const neighbor = reorderNeighbor(direction)
  if (!map.value || !neighbor) return
  const roots = selectionRoots.value, ids = new Set(roots.map(node => node.id))
  const nodes = map.value.nodes.filter(node => !ids.has(node.id))
  nodes.splice(nodes.findIndex(node => node.id === neighbor.id) + (direction > 0 ? 1 : 0), 0, ...roots)
  commit(nodes)
  focusNode(active.value.id, branchSelection.value)
}

function onMoveShortcut(event: KeyboardEvent): boolean {
  const { key, ctrlKey, metaKey, altKey, shiftKey } = event
  if (props.readonly || event.defaultPrevented || event.isComposing || !(ctrlKey || metaKey) || altKey || shiftKey
    || !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(key)) return false
  event.preventDefault()
  event.stopPropagation()
  const roots = selectionRoots.value
  const parent = byId.value.get(roots[0]?.parent ?? '')
  if (!parent || roots.some(node => node.parent !== parent.id)) return true
  const direction = key === 'ArrowDown' ? 1 : -1
  const target = key === 'ArrowLeft' ? parent : reorderNeighbor(direction)
  if (!target || (key === 'ArrowLeft' && parent.parent === null)) return true
  const placement = key === 'ArrowLeft' ? 'after' : 'inside'
  if ((key === 'ArrowLeft' || key === 'ArrowRight') && !branchDestination(roots, selectedSubtree.value, target, placement)) return true
  finishTitle(active.value.id)
  if (key === 'ArrowLeft' || key === 'ArrowRight') moveBranches(selectionRoots.value, target.id, placement)
  else reorder(direction)
  return true
}

function removeBranches(): void {
  const parent = selectionRoots.value[0]?.parent
  if (!map.value || !parent || !canMoveSelection.value || pendingRemove.value !== active.value.id) return
  const { ids } = selectedSubtree.value
  pendingRemove.value = null
  for (const id of ids) oversizedBodies.value.delete(id)
  commit(map.value.nodes.filter(node => !ids.has(node.id)), undefined,
    connectors.value.filter(link => !ids.has(link.source) && !ids.has(link.target)))
  focusNode(parent)
}

function confirmRemove(): void {
  if (!canMoveSelection.value) return
  pendingRemove.value = active.value.id
}

function storeBranches(mode: 'copy' | 'cut', transfer?: DataTransfer): void {
  if (props.readonly || !map.value || !selectionRoots.value.length || mode === 'cut' && !canMoveSelection.value) return
  const { ids, height } = selectedSubtree.value
  const token = crypto.randomUUID(), text = selectionRoots.value.map(node => node.title).join('\n')
  branchClipboard.value = mode === 'cut'
    ? { mode, token, text, ids: selectionRoots.value.map(node => node.id) }
    : { mode, token, text, nodes: map.value.nodes.filter(node => ids.has(node.id)),
      connectors: connectors.value.filter(link => ids.has(link.source) && ids.has(link.target)), height }
  if (transfer) {
    transfer.setData(branchClipboardMime, token)
    transfer.setData('text/plain', text)
  } else void copyToClipboard(text).catch(() => { /* The local branch clipboard still works from the toolbar. */ })
  $q.notify({ type: 'info', message: t(mode === 'cut' ? 'documents.mindmapClipboard.cutReady' : 'documents.mindmapClipboard.copied') })
}

function endCut(): boolean {
  const clip = branchClipboard.value
  if (clip?.mode !== 'cut') return false
  // Keep recognizing clipboard data from a cut that can no longer be pasted.
  branchClipboard.value = { mode: 'inactiveCut', token: clip.token, text: clip.text }
  return true
}

function cancelCut(): boolean {
  if (!endCut()) return false
  $q.notify({ type: 'info', message: t('documents.mindmapClipboard.cutCancelled') })
  return true
}

function cancelCutFromToolbar(): void {
  if (cancelCut()) focusNode(active.value.id, branchSelection.value)
}

function onCutEscape(event: KeyboardEvent): void {
  if (connectorNavigation.value || event.isComposing || !(event.target instanceof Element) || event.target.closest('.mindmap') !== event.currentTarget
    || !cancelCut()) return
  event.preventDefault()
  event.stopPropagation()
}

function pasteBranches(target: MindMapNode): void {
  const clip = branchClipboard.value, parent = target.id
  if (!clip || clip.mode === 'inactiveCut' || !map.value || !canPasteBranches(target)) return
  if (clip.mode === 'cut') {
    if (moveBranches(cutBranches.value, parent)) endCut()
    return
  }
  const ids = new Map(clip.nodes.map(node => [node.id, crypto.randomUUID()]))
  const nodes = clip.nodes.map(node => ({ ...node, id: ids.get(node.id)!, parent: ids.get(node.parent ?? '') ?? parent }))
  const links = clip.connectors.map(link => ({ ...link, source: ids.get(link.source)!, target: ids.get(link.target)! }))
  commit([...map.value.nodes, ...nodes], undefined, [...connectors.value, ...links])
  folded.value.delete(parent)
  focusBranches(nodes.filter(node => node.parent === parent))
}

function treeClipboardParent(event: ClipboardEvent): MindMapNode | undefined {
  const target = event.target
  if (props.readonly || event.defaultPrevented || !(target instanceof HTMLElement) || target.closest('.mindmap-canvas') !== canvas.value
    || target.closest('input, textarea, select') || target.isContentEditable && (activeBody.value || !target.hasAttribute('data-editor-surface'))) return
  const id = target.closest<HTMLElement>('[data-mindmap-node]')?.dataset.mindmapNode
  return id ? byId.value.get(id) : leavingTree.value ? undefined : byId.value.get(active.value.id)
}

function copyFromTree(event: ClipboardEvent, mode: 'copy' | 'cut'): void {
  if (!event.clipboardData || !treeClipboardParent(event) || !selectionRoots.value.length || mode === 'cut' && !canMoveSelection.value
    || window.getSelection()?.isCollapsed === false && !(event.target instanceof HTMLElement && event.target.hasAttribute('data-editor-surface'))) return
  storeBranches(mode, event.clipboardData)
  event.preventDefault()
  event.stopPropagation()
}

function pasteTextChildren(parentId: string, text: string): void {
  if (!text) return
  const lines = text.split(/\r\n?|\n/)
  if (lines.length > maxNodes) { $q.notify({ type: 'warning', message: t('richEditor.resources.failed') }); return }
  const branches = lines.map(title => {
    const uri = mindMapReferenceUri(title)
    if (uri) return linkChild(uri, title.trim())
    return Array.from(title).length > titleLength ? { title, body_html: mindMapParagraphHtml(title) } : { title }
  })
  appendChildren(parentId, branches)
}

function pasteIntoTree(event: ClipboardEvent): void {
  const parent = treeClipboardParent(event), data = event.clipboardData
  if (!parent || !data) return
  const clip = branchClipboard.value
  const token = data.getData(branchClipboardMime), text = data.getData('text/plain') || data.getData('text/uri-list')
  const files = Array.from(data.files)
  const internal = clip && (token === clip.token || !token && !files.length && text === clip.text)
  if (internal) pasteBranches(parent)
  else if (files.length && (props.uploadFile ?? props.uploadImage)) {
    endCut()
    void uploadResourceBranches(parent.id, files)
  } else if (text) {
    endCut()
    pasteTextChildren(parent.id, text)
  }
  else return
  event.preventDefault()
  event.stopPropagation()
}

async function pasteFromToolbar(): Promise<void> {
  const parent = active.value, current = map.value, clip = branchClipboard.value
  const unchanged = () => !disposed && !props.readonly && map.value === current && branchClipboard.value === clip
    && active.value.id === parent.id && !activeBody.value
  try {
    const text = await navigator.clipboard.readText()
    if (!unchanged()) return
    if (clip?.text === text) pasteBranches(parent)
    else if (text) {
      endCut()
      pasteTextChildren(parent.id, text)
    }
  } catch {
    if (!unchanged()) return
    if (canPasteBranches(parent)) pasteBranches(parent)
    else $q.notify({ type: 'negative', message: t('richEditor.clipboard.failed') })
  }
}

function startDrag(event: DragEvent, node: MindMapNode): void {
  if (props.readonly || node.parent === null || !event.dataTransfer) return
  const roots = selectedIds.value.has(node.id) ? selectionRoots.value : [node]
  if (roots.some(branch => branch.parent === null)) { event.preventDefault(); return }
  dragged.value = roots.map(branch => branch.id)
  event.dataTransfer.clearData()
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-galaris-mindmap-branch', node.id)
}

function stopDrag(): void { dragged.value = undefined; dropTarget.value = undefined }

function markDropTarget(id: string, placement: BranchPlacement): void {
  if (dropTarget.value?.id !== id || dropTarget.value.placement !== placement) dropTarget.value = { id, placement }
}

function branchPlacement(event: DragEvent, node: MindMapNode): BranchPlacement {
  if (node.parent === null || !(event.currentTarget instanceof HTMLElement)) return 'inside'
  const bounds = event.currentTarget.getBoundingClientRect()
  const edge = Math.min(bounds.height / 4, 14 * bounds.height / Math.max(1, event.currentTarget.offsetHeight))
  if (event.clientY < bounds.top + edge) return 'before'
  if (event.clientY > bounds.bottom - edge) return 'after'
  return 'inside'
}

function hoverBranch(event: DragEvent, node: MindMapNode): void {
  if (!dragged.value || event.defaultPrevented) return
  const placement = branchPlacement(event, node)
  if (!branchDestination(dragBranches.value, dragSubtree.value, node, placement)) {
    dropTarget.value = undefined
    return
  }
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  markDropTarget(node.id, placement)
}

function leaveBranch(event: DragEvent, id: string): void {
  if (dropTarget.value?.id === id && !(event.currentTarget instanceof HTMLElement && event.relatedTarget instanceof Node
    && event.currentTarget.contains(event.relatedTarget))) dropTarget.value = undefined
}

function dropBranch(event: DragEvent, target: MindMapNode): void {
  if (!dragged.value || event.defaultPrevented) return
  event.preventDefault()
  event.stopPropagation()
  moveBranches(dragBranches.value, target.id, branchPlacement(event, target))
  stopDrag()
}

function navigateBranches(event: KeyboardEvent, node: MindMapNode): void {
  const branch = children.value.get(node.id)?.[0]
  const extend = event.shiftKey && !event.altKey
  let target: string | undefined
  if (event.key === 'ArrowLeft' && node.parent) target = node.parent
  else if (event.key === 'ArrowRight' && branch) {
    folded.value.delete(node.id)
    target = branch.id
  } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
    const peers = extend ? visibleNodes.value : children.value.get(node.parent) ?? []
    const index = peers.findIndex(peer => peer.id === node.id)
    target = peers[index + (event.key === 'ArrowDown' ? 1 : -1)]?.id
  }
  if (target) focusNode(target, extend ? { kind: 'range', anchor: selectionAnchor.value ?? node.id } : undefined)
  event.preventDefault()
  event.stopPropagation()
}

function onTreeKeydown(event: KeyboardEvent, inputNode?: MindMapNode): void {
  const id = event.target instanceof HTMLElement ? event.target.dataset.mindmapNode : undefined
  const node = inputNode ?? (id ? byId.value.get(id) : undefined)
  if (!node || event.isComposing || event.defaultPrevented) return
  if (onNodeShortcut(event, node)) return
  if (onMoveShortcut(event)) return
  if ((event.ctrlKey || event.metaKey) && !event.altKey) {
    const key = event.key.toLowerCase()
    if (key === 'f' && !event.shiftKey) openSearch()
    else if (key === 'a' && !event.shiftKey) selectAllBranches()
    else if (!props.readonly && key === 'z') restoreHistory(event.shiftKey ? 'redo' : 'undo')
    else if (!props.readonly && key === 'y' && !event.shiftKey) restoreHistory('redo')
    else if (key !== 'k') return
    if (key !== 'k') { event.preventDefault(); event.stopPropagation(); return }
  }
  const text = props.readonly || (event.key === ' ' && node.value == null) ? undefined : typedCharacter(event)
  if (text) {
    event.preventDefault()
    event.stopPropagation()
    if (node.value == null) focusTitle(node.id, text)
    else {
      const input = valueInput(node.id)
      if (!input) return
      focusNode(node.id)
      const position = input.value.length
      if (position + text.length <= maxValueLength) {
        setNodeValue(node.id, input.value + text)
        void nextTick(() => input.setSelectionRange(position + text.length, position + text.length))
      }
    }
    return
  }
  if (event.altKey) {
    if (!event.ctrlKey && !event.metaKey && !event.shiftKey && event.key === 'ArrowRight') {
      navigateBranches(event, node)
      return
    }
    if (!event.ctrlKey && !event.metaKey && (event.key === '0' || event.code === 'Digit0')) helpOpen.value = true
    else if (!event.ctrlKey && !event.metaKey && event.key === 'Delete' && canMoveSelection.value) confirmRemove()
    else if (event.key === 'Enter' && !props.readonly) openBody(node.id)
    else return
    event.preventDefault()
    event.stopPropagation()
    return
  }
  const branch = children.value.get(node.id)?.[0]
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !props.readonly) openLinkDialog(node)
  else if (event.ctrlKey || event.metaKey) return
  else if (event.key.startsWith('Arrow')) {
    if (event.key !== 'ArrowRight' || event.shiftKey || !followConnector(node.id, event.repeat)) {
      navigateBranches(event, node)
      return
    }
  }
  else if (event.key === ' ' && node.checked != null && !props.readonly) toggleCheckboxes(node)
  else if (event.key === ' ' && branch) toggleFold(node.id)
  else if (event.key === 'Escape') {
    if (fullscreen.value) { onFullscreenEscape(event); return }
    clearSelectionActions()
    branchSelection.value = undefined
    leavingTree.value = true
    canvas.value?.focus({ preventScroll: true })
  } else if (!props.readonly && !event.shiftKey) {
    if ((event.key === 'Tab' || event.key === 'Insert') && canAdd(node)) addBranch(node)
    else if (event.key === 'Enter') focusTitle(node.id)
    else if (event.key === 'Delete' && canMoveSelection.value) confirmRemove()
    else return
  } else if (!props.readonly && event.shiftKey && event.key === 'Enter') {
    if (node.parent === null) addBranch(node)
    else addSibling()
  } else if (event.key === 'F3') toggleDetails(node.id)
  else return
  event.preventDefault()
  event.stopPropagation()
}

function followConnector(id: string, repeat = false): boolean {
  const links = connectorsByNode.value.get(id)
  if (!links?.length) return false
  if (repeat) return true
  if (links.length === 1) jumpToConnector(links[0]!.other.id)
  else selectConnectorForNavigation(id, links[0]!)
  return true
}

function selectConnectorForNavigation(origin: string, { connector, other }: ConnectedNode): void {
  const key = connectorKey(connector)
  connectorNavigation.value = { origin, key, destination: other.id, label: connector.label }
  unfoldAncestors(other)
  void nextTick(() => {
    if (connectorNavigation.value?.key !== key) return
    const path = stage.value?.parentElement?.querySelector<SVGElement>(`.mindmap-connectors > [data-connector-key="${key}"]`)
    if (path) path.focus({ preventScroll: true })
    else connectorNavigation.value = undefined
  })
}

function leaveConnectorNavigation(key: string): void {
  if (connectorNavigation.value?.key === key) connectorNavigation.value = undefined
}

function onConnectorNavigationKeydown(event: KeyboardEvent, key: string): void {
  const choice = connectorNavigation.value
  if (choice?.key !== key || event.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey
    || !['ArrowUp', 'ArrowDown', 'ArrowRight', 'Escape'].includes(event.key)) return
  event.stopPropagation()
  event.preventDefault()
  const links = connectorsByNode.value.get(choice.origin) ?? []
  const index = links.findIndex(link => connectorKey(link.connector) === key)
  if (event.key === 'Escape' || index < 0) {
    connectorNavigation.value = undefined
    focusNode(choice.origin)
  } else if (event.key === 'ArrowRight') {
    if (!event.repeat) jumpToConnector(links[index]!.other.id)
  } else {
    const next = (index + links.length + (event.key === 'ArrowDown' ? 1 : -1)) % links.length
    selectConnectorForNavigation(choice.origin, links[next]!)
  }
}

function discardDraft(): void {
  history.clear()
  connectorNodeId.value = undefined
  connectorRemoval.value = undefined
  connectorEdit.value = undefined
  connectorNavigation.value = undefined
  endCut()
  editing.value = null
  editingTitle.value = undefined
  editingBody.value = undefined
  pendingBody.value = undefined
  clearSelectionActions()
  uploadRequest?.abort()
  oversizedBodies.value.clear()
  const title = titleElement(active.value.id)
  if (title) title.textContent = active.value.title
}

defineExpose({ commitDraft, discardDraft, insertResource })
</script>


<style scoped>
.mindmap {
  --map-line: var(--map-canvas-ink, color-mix(in srgb, var(--solaire-gray-accent) 68%, transparent));
  --map-neutral: var(--solaire-gray-light);
  --map-shadow-color: rgb(0 0 0 / 9%);
  --map-branch-gap: 2.5rem;
  --map-elbow: 1.25rem;
  --map-radius: .55rem;
  --map-row-gap: .375rem;
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.mindmap.editorial-fullscreen { background: var(--galaris-page-background, var(--map-neutral)); overscroll-behavior: contain; }
.mindmap--dark {
  --map-neutral: var(--solaire-gray-dark);
  --map-shadow-color: rgb(0 0 0 / 26%);
}
.mindmap-rich-body:not(.mindmap-inspecting-resource) :deep(.rich-content-reader :is(.galaris-resource-embed, [data-document-player], iframe)) { pointer-events: none; }
.mindmap-inspecting-resource { position: relative; }
.mindmap-inspecting-resource > :deep(.rich-editor) { position: absolute; inset: 0; clip-path: inset(50%); pointer-events: none; }
.mindmap-inspecting-resource :deep([data-editor-surface] > *) { visibility: hidden; }
.mindmap-inspecting-resource :deep(.mindmap-selected-image) { position: relative; }
.mindmap-inspecting-resource :deep(.mindmap-selected-image > .galaris-image-resize) { display: block; }
.mindmap-tools { justify-content: center; }
.mindmap-selection-count { padding: .1rem .5rem; font-size: .75rem; }
.mindmap-theme-options { display: grid; gap: .25rem; }
.mindmap-theme-option { display: inline-flex; align-items: center; gap: .75rem; }
.mindmap-theme-swatches { display: inline-flex; gap: .2rem; }
.mindmap-theme-swatch { display: inline-block; inline-size: 1.15rem; block-size: .75rem; border: 1px solid; border-radius: .25rem; }
.mindmap-scrollbar {
  appearance: none;
  position: sticky;
  bottom: 0;
  z-index: 2;
  flex: none;
  display: block;
  width: 100%;
  height: 8px;
  margin: 0;
  background: var(--map-neutral);
  cursor: pointer;
  touch-action: none;
}
.mindmap-scrollbar::-webkit-slider-thumb {
  appearance: none;
  width: max(2rem, var(--mindmap-scroll-thumb));
  height: 6px;
  border-radius: 3px;
  background: var(--solaire-gray-accent);
}
.mindmap-scrollbar::-moz-range-thumb {
  width: max(2rem, var(--mindmap-scroll-thumb));
  height: 6px;
  border: 0;
  border-radius: 3px;
  background: var(--solaire-gray-accent);
}
.mindmap-scrollbar:focus-visible { outline: 1px solid var(--solaire-blue-accent); outline-offset: -1px; }
.mindmap-canvas {
  position: relative;
  flex: 1 0 auto;
  overflow-x: auto;
  overflow-y: hidden;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
  touch-action: none;
  cursor: grab;
  outline: none;
  -webkit-user-select: none;
  user-select: none;
}
.mindmap-title,
.mindmap-canvas :deep(:is(input:not([readonly]), textarea:not([readonly]))),
.mindmap-editing-body :deep([data-editor-surface][contenteditable="true"]) {
  -webkit-user-select: text;
  user-select: text;
}
.mindmap-plane { position: relative; overflow: clip; }
.mindmap-connectors { position: absolute; top: 0; transform-origin: top left; overflow: visible; pointer-events: none; }
.mindmap-root--connected { z-index: 1; pointer-events: none; }
.mindmap-root--connected .mindmap-node { pointer-events: auto; }
.mindmap-connector-line { fill: none; stroke: var(--solaire-iris-accent); stroke-width: 1.6; stroke-dasharray: 5 3; }
.mindmap-connector--active:focus { outline: none; }
.mindmap-connector--active .mindmap-connector-line { stroke: var(--solaire-blue-accent); stroke-width: 3.2; }
.mindmap-connector--active .mindmap-connector-label { font-weight: 700; }
.mindmap-connector-hit { fill: none; stroke: transparent; stroke-width: 14px; pointer-events: stroke; cursor: pointer; }
.mindmap-connector-arrow { fill: var(--solaire-iris-accent); }
.mindmap-connector-label {
  fill: var(--rich-foreground, currentColor);
  stroke: var(--map-neutral);
  stroke-width: 3px;
  paint-order: stroke;
  font-size: .75rem;
  pointer-events: all;
  cursor: pointer;
}
.mindmap-panning { cursor: grabbing; }
.mindmap-root {
  position: absolute;
  inset: 0 auto auto 0;
  transform-origin: top left;
  width: max-content;
  padding: 1.15rem 1.5rem 1.5rem .85rem;
  margin: 0;
  list-style: none;
}
.mindmap-node {
  --map-accent: var(--map-level-0-accent);
  --map-tint: var(--map-level-0-tint);
  --map-border-accent: 34%;
  --map-node-radius: .4rem;
  --map-resource-border: initial;
  max-width: min(24rem, 74vw);
  min-width: 0;
  color: var(--rich-foreground, inherit);
  font-size: .875rem;
  line-height: 1.3;
  background: var(--map-tint);
  border: 1px solid var(--map-resource-border, color-mix(in srgb, var(--map-accent) var(--map-border-accent), var(--map-canvas-ink, transparent)));
  border-radius: var(--map-node-radius);
  box-shadow: 0 1px 3px var(--map-shadow-color);
}
.mindmap-root :deep([data-level="0"]) > .mindmap-node { font-size: 1.06rem; font-weight: 650; }
.mindmap-root :deep([data-level="1"]) > .mindmap-node { --map-accent: var(--map-level-1-accent); --map-tint: var(--map-level-1-tint); font-weight: 590; }
.mindmap-root :deep([data-level="2"]) > .mindmap-node { --map-accent: var(--map-level-2-accent); --map-tint: var(--map-level-2-tint); }
.mindmap-root :deep([data-level="3"]) > .mindmap-node { --map-accent: var(--map-level-3-accent); --map-tint: var(--map-level-3-tint); }
.mindmap-node--cut { opacity: .5; }
.mindmap:focus-within .mindmap-root :deep([aria-selected="true"]) > .mindmap-node {
  background: color-mix(in srgb, var(--map-accent) 16%, var(--map-tint));
  border-color: var(--map-resource-border, var(--map-accent));
  outline: 1px solid var(--map-resource-border, var(--map-accent));
}
.mindmap-node.mindmap-resource-only:not(.mindmap-card-node, .mindmap-embedded-node) {
  border: 0;
  background: transparent;
}
.mindmap-node.mindmap-resource-only:not(.mindmap-card-node, .mindmap-embedded-node, [data-drop-placement]) {
  box-shadow: none;
}
.mindmap-node[data-drop-placement="inside"] { box-shadow: inset 0 0 0 2px var(--solaire-blue-accent); }
.mindmap-node[data-drop-placement="before"] { box-shadow: 0 -3px var(--solaire-blue-accent); }
.mindmap-node[data-drop-placement="after"] { box-shadow: 0 3px var(--solaire-blue-accent); }
:is(.mindmap-card-node, .mindmap-embedded-node) { --map-border-accent: 60%; }
.mindmap-resource-only .mindmap-rich-body { width: fit-content; max-width: min(20rem, 62vw); }
.mindmap-checkable { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; }
.mindmap-checkable > :not(.mindmap-node-checkbox) { grid-column: 2; min-width: 0; }
.mindmap-node-checkbox { min-width: 1.65rem; min-height: 1.65rem; justify-content: center; }
.mindmap-node-line, .mindmap-link-node > .mindmap-details { min-height: 1.65rem; }
.mindmap-node-line { display: flex; gap: .1rem; align-items: center; padding-inline: .5rem .2rem; }
.mindmap-value-input {
  flex: 0 0 auto;
  width: clamp(4rem, 18vw, 9rem);
  margin-inline-start: .25rem;
  padding: .1rem .35rem;
  border: 0;
  border-radius: 0;
  background: white;
  color: #292c30;
  font: inherit;
  font-weight: 400;
}
.mindmap--dark .mindmap-value-input { background: #101010; color: #eeeef0; }
.mindmap-value-input:focus { outline: none; }
.mindmap-rich-parent { position: relative; }
.mindmap-rich-parent > .mindmap-details { padding-inline-end: 1.95rem; }
.mindmap-rich-fold { position: absolute; inset-block-start: .2rem; inset-inline-end: .2rem; }
.mindmap-label { display: block; min-width: 0; padding-block: .15rem; overflow-wrap: anywhere; white-space: pre-wrap; cursor: pointer; }
.mindmap-title { outline: none; cursor: text; }
.mindmap-label:empty { min-inline-size: 1ch; min-block-size: calc(1lh + .3rem); }
.mindmap-details { padding: .4rem .55rem; overflow-wrap: anywhere; }
.mindmap-details p { margin: 0; white-space: pre-wrap; }
.mindmap-details p + p { margin-top: .35rem; }
.mindmap-rich-body { --document-embed-width: min(20rem, 62vw); --document-text-embed-width: min(17rem, 55vw); width: min(20rem, 62vw); max-width: 100%; font-weight: 400; }
.mindmap-node:has(> .mindmap-details > .mindmap-rich-body .document-reference-reader) { max-width: min(210mm, 94vw); }
.mindmap-rich-body:has(.document-reference-reader) { width: fit-content; max-width: 100%; }
.mindmap-rich-body :deep(.rich-editor),
.mindmap-rich-body :deep(.editorial-body),
.mindmap-rich-body :deep([data-editor-surface]) { background: transparent; }
.mindmap-rich-body :deep(.rich-content) {
  border: 0;
  padding: .25rem 0;
  font-size: inherit;
}
.mindmap-link-node > .mindmap-details {
  display: flex;
  align-items: center;
  padding-block: .15rem;
  padding-inline-start: .5rem;
}
.mindmap-link-node:not(.mindmap-rich-parent) > .mindmap-details { padding-inline-end: .2rem; }
.mindmap-link-node .mindmap-rich-body { width: fit-content; font-weight: inherit; }
.mindmap-link-node .mindmap-rich-body :deep([data-editor-surface]) { min-height: 0; }
.mindmap-link-node .mindmap-rich-body :deep(.rich-content),
.mindmap-standalone-link :deep(.rich-content) { padding: 0; font-size: inherit; line-height: inherit; }
.mindmap-link-node .mindmap-rich-body :deep(.rich-content > p),
.mindmap-standalone-link :deep(.rich-content > p) { margin: 0; }
.mindmap-rich-body :deep(blockquote.galaris-link-card:not([data-resource-mode="embed"])) { background: transparent; border: 0; box-shadow: none; }
:is(.mindmap-card-node, .mindmap-embedded-node) > .mindmap-details:has(> .mindmap-rich-body),
:is(.mindmap-card-node, .mindmap-embedded-node) > .mindmap-details > .mindmap-rich-body :deep(.rich-content) { padding: 0; }
.mindmap-card-node.mindmap-rich-parent .mindmap-rich-body { margin-inline-end: 1.95rem; }
:is(.mindmap-card-node, .mindmap-embedded-node) :deep(.rich-content > blockquote.galaris-link-card) {
  margin: 0;
  padding: 0;
  border-radius: .35rem;
}
.mindmap-embedded-node :deep(.rich-content > blockquote.galaris-link-card) { min-height: 0; }
.mindmap-embedded-node :deep(.rich-content > blockquote.galaris-link-card > p) { margin: 0; }
.mindmap-embedded-node :deep(.rich-content > blockquote.galaris-link-card > p:first-child) { padding-block-start: 2px; }
.mindmap-embedded-node.mindmap-rich-parent :deep(.rich-content > blockquote.galaris-link-card > p:first-child) { padding-inline-end: 1.95rem; }
.mindmap-card-node :deep(.rich-content > blockquote.galaris-agent-card) { --map-card-thumbnail-width: min(112px, 27vw); }
.mindmap-card-node :deep(.rich-content > blockquote.galaris-document-card) { --map-card-thumbnail-width: min(100px, 27vw); }
.mindmap-card-node :deep(.rich-content > :is(.galaris-agent-card, .galaris-document-card)) { align-content: center; }
.mindmap-card-node :deep(.rich-content > :is(.galaris-agent-card, .galaris-document-card) > :is(p, .galaris-resource-embed:has(.document-citation-preview))) {
  margin-inline-start: calc(var(--map-card-thumbnail-width) + .5rem);
}
.mindmap-card-node :deep(.rich-content > :is(.galaris-agent-card, .galaris-document-card) > .galaris-resource-embed:not(:has(.document-citation-preview))),
.mindmap-card-node :deep(.rich-content > .galaris-document-card .document-citation-thumbnail) {
  inset: 0 auto 0 0;
  width: var(--map-card-thumbnail-width);
}
.mindmap-rich-body :deep(blockquote.galaris-link-card.image) { padding: 0; margin: 0; background: transparent; }
.mindmap-rich-body :deep(blockquote.galaris-link-card.image a img) { display: block; }
.mindmap-image-node > .mindmap-details,
.mindmap-image-node .mindmap-rich-body :deep(.rich-content) { padding: 0; }
.mindmap-image-node :deep(.rich-content > :is(figure.image, p, blockquote.image)) { margin: 0; float: none; }
.mindmap-image-node :deep(.rich-content :is(img, a:has(img))) { display: block; }
.mindmap-rich-body :deep(.galaris-image-object) { min-inline-size: 12px; min-block-size: 12px; }
.mindmap-rich-body :deep(.galaris-image-object img) { min-width: 0; min-height: 0; }
.mindmap-rich-body :deep(.galaris-image-resize) { right: 0; bottom: 0; }
.mindmap-rich-body :deep(blockquote.galaris-link-card.ProseMirror-selectednode:not([data-resource-mode="embed"][data-resource-border])) { outline: none; }
.mindmap-rich-body :deep(blockquote.galaris-link-card[data-resource-mode="embed"][data-resource-border].ProseMirror-selectednode) {
  outline: 1px solid var(--document-embed-border);
}
.mindmap-embedded-node > .mindmap-details > .mindmap-rich-body :deep(.rich-content > blockquote.galaris-link-card[data-resource-border]) { outline: none; }
/* The node frames its own standalone reader, including when the rich editor is active. */
.mindmap-embedded-node[data-embedded-kind="document"] > .mindmap-details > .mindmap-rich-body
  > :deep(.rich-content-reader > .rich-content > blockquote > .galaris-resource-embed > .document-reference-reader
  > .document-reference-viewport > .document-resource-embed > .document-text-embed),
.mindmap-embedded-node[data-embedded-kind="document"] > .mindmap-details > .mindmap-rich-body
  > :deep(.rich-editor > .editorial-workspace > .editorial-body > div > [data-editor-surface] > blockquote
  > .galaris-resource-embed > .document-reference-reader > .document-reference-viewport > .document-resource-embed > .document-text-embed) {
  border-color: transparent;
  border-radius: 0 0 calc(var(--map-node-radius) - 1px) calc(var(--map-node-radius) - 1px);
}
.mindmap-embedded-node[data-embedded-kind="process"] :deep(.process-preview--inline .diagram-editor:not(.fullscreen)) {
  --map-diagram-radius: calc(var(--map-node-radius) - 1px);
  border: 0;
  border-radius: 0 0 var(--map-diagram-radius) var(--map-diagram-radius);
}
.mindmap-node:not(.mindmap-card-node) .mindmap-rich-body :deep(blockquote.galaris-link-card:not(.image, [data-resource-mode="embed"]).ProseMirror-selectednode) {
  background-color: color-mix(in srgb, var(--map-accent) 12%, transparent);
}
.mindmap-rich-body :deep(.rich-content :is(.galaris-image-object, figure.image, span.image-inline, blockquote.galaris-link-card.image, img)) {
  border: 0;
  outline: none;
}
.mindmap-rich-body :deep([data-editor-surface]) {
  touch-action: pan-y;
}
@media (max-width: 1023px) {
  .mindmap { --map-branch-gap: 1.2rem; --map-elbow: .6rem; }
}
</style>
