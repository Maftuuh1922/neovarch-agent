// The chat composer's desktop-parity controls on the phone: the "+" liquid
// glass menu (Foto/Kamera/File/Tempel, Skill, Model, Penalaran, file/folder
// mentions, URL, prompt snippets), the selection chips above the field, the
// "/" and "@" suggestion list, and the accent-tinted prominent send button.
//
// Liquid glass rules (liquid-glass-spec.md): glass only on the control layer
// (the composer and the sheet are glass; chips, tiles and rows inside them are
// thin fills, never glass-on-glass), one prominent tinted control (send), every
// colour derived from the theme accent, text >= 4.5:1 and glyphs >= 3:1.
import 'dart:math' as math;

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart' show toast;
import '../composer.dart';
import '../remote_controller.dart';
import 'nv_widgets.dart';
import 'remote_attachments.dart';

// ----------------------------------------------------------------- colour --
double _lum(Color c) {
  double ch(double v) => v <= 0.03928 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b);
}

/// WCAG contrast ratio of two opaque colours.
double composerContrast(Color a, Color b) {
  final la = _lum(a), lb = _lum(b);
  return (math.max(la, lb) + 0.05) / (math.min(la, lb) + 0.05);
}

/// What sits under the composer at rest: the glass fill over the page.
Color composerGlassBase() => Color.alphaBlend(NV.glass, NV.bg);

/// Prominent (tinted) glass: the accent wash at 0.80 over the glass base.
Color prominentFill() => Color.alphaBlend(NV.red.withValues(alpha: 0.80), composerGlassBase());

/// Black or white, whichever reads better on [bg] (always >= 4.5:1).
Color inkOn(Color bg) {
  const w = Color(0xFFFFFFFF), k = Color(0xFF000000);
  return composerContrast(w, bg) >= composerContrast(k, bg) ? w : k;
}

/// Chip fill: a thin accent wash (not glass) over the composer glass.
Color chipFill({bool selected = false}) =>
    Color.alphaBlend(NV.red.withValues(alpha: selected ? (NV.palette.dark ? 0.26 : 0.18) : (NV.palette.dark ? 0.10 : 0.07)), composerGlassBase());

/// The accent pushed toward the text colour until it reaches [min]:1 on [bg]
/// (accent glyphs on light themes, e.g. Monokrom / Kuning).
Color accentInk(Color bg, {double min = 3.0}) {
  var c = NV.red;
  for (var i = 1; i <= 10 && composerContrast(c, bg) < min; i++) {
    c = Color.lerp(NV.red, NV.text, i / 10)!;
  }
  return c;
}

/// Secondary text on [bg]: the muted token, nudged toward the text colour
/// until it reaches 4.5:1 (thin chip washes on some accents).
Color mutedOn(Color bg) {
  var c = NV.muted;
  for (var i = 1; i <= 10 && composerContrast(c, bg) < 4.5; i++) {
    c = Color.lerp(NV.muted, NV.text, i / 10)!;
  }
  return c;
}

// --------------------------------------------------------------- buttons --
/// "+" at the left of the field: a thin fill inside the composer glass.
class ComposerPlusButton extends StatelessWidget {
  const ComposerPlusButton({super.key, required this.onPressed, this.open = false});
  final VoidCallback? onPressed;
  final bool open;
  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    final bg = chipFill(selected: open);
    return Tooltip(
      message: 'Lampiran, skill, model, dan lainnya',
      child: Semantics(
        button: true,
        label: 'Menu komposer',
        child: Material(
          color: bg,
          shape: CircleBorder(side: BorderSide(color: NV.glassBorder)),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onPressed,
            child: SizedBox(
              width: 40,
              height: 40,
              child: AnimatedRotation(
                turns: open ? 0.125 : 0,
                duration: const Duration(milliseconds: 180),
                // inside the chat's liquid glass: the glass tone's foreground
                child: Icon(CupertinoIcons.add, size: 20, color: enabled ? (DefaultTextStyle.of(context).style.color ?? NV.text) : NV.faint),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The one prominent control: accent-tinted glass (wash 0.80 + rim), label
/// black or white by contrast. Replaces the old solid red send button.
class ComposerSendButton extends StatelessWidget {
  const ComposerSendButton({super.key, required this.onPressed, this.stop = false});
  final VoidCallback? onPressed;
  final bool stop;
  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    final fill = enabled ? prominentFill() : chipFill();
    final ink = enabled ? inkOn(fill) : NV.faint;
    final br = BorderRadius.circular(20);
    return Tooltip(
      message: stop ? 'Hentikan' : 'Kirim',
      child: Semantics(
        button: true,
        label: stop ? 'Hentikan' : 'Kirim',
        child: CustomPaint(
          foregroundPainter: enabled ? NvGlassRimPainter(borderRadius: br, rim: NV.glassRim) : null,
          child: Material(
            key: const ValueKey('composer-send-fill'),
            color: enabled ? NV.red.withValues(alpha: 0.80) : fill,
            shape: RoundedRectangleBorder(borderRadius: br, side: BorderSide(color: enabled ? NV.red.withValues(alpha: 0.9) : NV.glassBorder)),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: onPressed,
              child: SizedBox(
                width: 40,
                height: 40,
                child: Icon(stop ? CupertinoIcons.stop_fill : CupertinoIcons.arrow_up, size: stop ? 16 : 20, color: ink),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------ chips --
class ComposerChip extends StatelessWidget {
  const ComposerChip({super.key, required this.label, this.icon, this.onTap, this.onRemove, this.selected = false, this.busy = false});
  final String label;
  final IconData? icon;
  final VoidCallback? onTap;
  final VoidCallback? onRemove;
  final bool selected;
  final bool busy;
  @override
  Widget build(BuildContext context) {
    final bg = chipFill(selected: selected);
    return Semantics(
      button: onTap != null,
      label: label,
      child: Material(
        color: bg,
        shape: StadiumBorder(side: BorderSide(color: selected ? NV.red.withValues(alpha: 0.45) : NV.glassBorder)),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: EdgeInsets.fromLTRB(10, 6, onRemove != null ? 4 : 11, 6),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (busy)
                SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 1.6, color: accentInk(bg)))
              else if (icon != null)
                Icon(icon, size: 14, color: selected ? accentInk(bg) : mutedOn(bg)),
              if (icon != null || busy) const SizedBox(width: 6),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 170),
                child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: NV.text, height: 1.2)),
              ),
              if (onRemove != null)
                InkResponse(
                  onTap: onRemove,
                  radius: 14,
                  child: Padding(padding: const EdgeInsets.all(3), child: Icon(CupertinoIcons.xmark, size: 12, color: mutedOn(bg))),
                ),
            ]),
          ),
        ),
      ),
    );
  }
}

String shortModel(String m) {
  if (m.isEmpty) return 'Model';
  final s = m.split('/').last;
  return s.length > 26 ? '${s.substring(0, 25)}…' : s;
}

/// Whether [ComposerChipsRow] shows the model chip (the PC sent a composer
/// catalog with a model). The chat screen shows its fallback [ModelChip]
/// (model_picker.dart) only when this is false, so the composer never lists
/// the model twice (cube chip + sparkle chip).
bool composerShowsModel(RemoteController r) {
  final c = r.composer;
  return c != null && (c.hasModels || c.model.isNotEmpty);
}

/// Current selections above the field: model, reasoning effort, skills.
/// Empty (nothing rendered) when the PC has no composer catalog.
class ComposerChipsRow extends StatelessWidget {
  const ComposerChipsRow({super.key, required this.r, required this.onModel, required this.onReasoning, required this.onSkills});
  final RemoteController r;
  final VoidCallback onModel, onReasoning, onSkills;
  @override
  Widget build(BuildContext context) {
    final c = r.composer;
    if (c == null) return const SizedBox.shrink();
    final chips = <Widget>[
      if (composerShowsModel(r))
        ComposerChip(
          key: const ValueKey('chip-model'),
          icon: CupertinoIcons.cube,
          label: shortModel(c.model),
          busy: r.modelSwitching,
          onTap: r.connected && c.hasModels ? onModel : null,
        ),
      if (c.canSendEffort)
        ComposerChip(
          key: const ValueKey('chip-reasoning'),
          icon: CupertinoIcons.lightbulb,
          label: 'Penalaran: ${c.effortLabel(r.reasoningEffort)}',
          selected: r.reasoningEffort != null,
          onTap: r.connected ? onReasoning : null,
        ),
      for (final s in r.selectedSkills)
        ComposerChip(
          key: ValueKey('chip-skill-$s'),
          icon: CupertinoIcons.sparkles,
          label: '/$s',
          selected: true,
          onTap: onSkills,
          onRemove: () => r.toggleSkill(s),
        ),
    ];
    if (chips.isEmpty) return const SizedBox.shrink();
    return SizedBox(
      key: const ValueKey('composer-chips'),
      height: 40,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(4, 4, 4, 4),
        itemCount: chips.length,
        separatorBuilder: (_, _) => const SizedBox(width: 6),
        itemBuilder: (_, i) => chips[i],
      ),
    );
  }
}

// ------------------------------------------------------------ suggestions --
/// "/" or "@" suggestions, inside the composer (thin rows, not glass).
class ComposerSuggestionList extends StatelessWidget {
  const ComposerSuggestionList({super.key, required this.items, required this.onPick, required this.kind, this.loading = false});
  final List<ComposerSuggestion> items;
  final ValueChanged<ComposerSuggestion> onPick;
  final String kind;
  final bool loading;
  @override
  Widget build(BuildContext context) {
    final head = kind == '/' ? 'Skill & perintah' : 'Sebut file, folder, atau konteks di PC';
    return Container(
      key: const ValueKey('composer-suggestions'),
      constraints: const BoxConstraints(maxHeight: 232),
      margin: const EdgeInsets.fromLTRB(2, 2, 2, 6),
      decoration: BoxDecoration(color: chipFill(), borderRadius: BorderRadius.circular(14), border: Border.all(color: NV.glassBorder)),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Row(children: [
            Expanded(child: Text(head, style: NV.monoLabel(size: 9.5, color: mutedOn(chipFill())))),
            if (loading) SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 1.5, color: NV.muted)),
          ]),
        ),
        if (items.isEmpty && !loading)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 10),
            child: Text('Tidak ada yang cocok', style: TextStyle(fontSize: 13, color: mutedOn(chipFill()))),
          )
        else
          Flexible(
            child: ListView.builder(
              shrinkWrap: true,
              padding: const EdgeInsets.only(bottom: 4),
              itemCount: items.length,
              itemBuilder: (_, i) {
                final it = items[i];
                final icon = switch (it.kind) {
                  'skill' => CupertinoIcons.sparkles,
                  'command' => CupertinoIcons.command,
                  'folder' => CupertinoIcons.folder,
                  'file' => CupertinoIcons.doc,
                  _ => CupertinoIcons.at,
                };
                return InkWell(
                  key: ValueKey('suggestion-${it.text}'),
                  onTap: () => onPick(it),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    child: Row(children: [
                      Icon(icon, size: 15, color: it.kind == 'skill' ? accentInk(chipFill()) : NV.muted),
                      const SizedBox(width: 10),
                      Flexible(
                        child: Text(it.display, maxLines: 1, overflow: TextOverflow.ellipsis,
                            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: NV.text)),
                      ),
                      if (it.meta.isNotEmpty) ...[
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(it.meta, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: mutedOn(chipFill()))),
                        ),
                      ],
                    ]),
                  ),
                );
              },
            ),
          ),
      ]),
    );
  }
}

// ------------------------------------------------------------------ sheet --
/// A liquid-glass bottom sheet (large glass: more opaque fill, inset from
/// the screen edges, radius 28).
Future<T?> showGlassSheet<T>(BuildContext context, {required WidgetBuilder builder, bool tall = false}) => showModalBottomSheet<T>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      elevation: 0,
      showDragHandle: false,
      shape: const RoundedRectangleBorder(),
      barrierColor: Colors.black.withValues(alpha: NV.palette.dark ? 0.35 : 0.18),
      builder: (ctx) {
        final kb = MediaQuery.viewInsetsOf(ctx).bottom;
        final pad = MediaQuery.paddingOf(ctx).bottom;
        final maxH = MediaQuery.sizeOf(ctx).height * (tall ? 0.82 : 0.72);
        return Padding(
          padding: EdgeInsets.fromLTRB(10, 0, 10, (kb > 0 ? kb : pad) + 10),
          child: ConstrainedBox(
            constraints: BoxConstraints(maxHeight: maxH),
            child: NvGlass(
              key: const ValueKey('glass-sheet'),
              radius: 28,
              tint: Color.lerp(NV.surface, NV.red, NV.palette.dark ? 0.08 : 0.05)!.withValues(alpha: NV.palette.dark ? 0.80 : 0.84),
              child: Material(type: MaterialType.transparency, child: builder(ctx)),
            ),
          ),
        );
      },
    );

class _SheetHead extends StatelessWidget {
  const _SheetHead(this.kicker, this.title, {this.trailing});
  final String kicker, title;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 14, 8),
        child: Column(children: [
          Container(width: 36, height: 4, decoration: BoxDecoration(color: NV.muted.withValues(alpha: 0.45), borderRadius: BorderRadius.circular(2))),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(kicker, style: NV.monoLabel(size: 9.5, color: NV.muted)),
                const SizedBox(height: 2),
                Text(title, style: NV.display(size: 22)),
              ]),
            ),
            ?trailing,
          ]),
        ]),
      );
}

class _Tile extends StatelessWidget {
  const _Tile({super.key, required this.icon, required this.label, required this.onTap});
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    final bg = chipFill();
    return Expanded(
      child: Material(
        color: bg,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: NV.glassBorder)),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 4),
            child: Column(children: [
              Icon(icon, size: 22, color: onTap == null ? NV.faint : accentInk(bg)),
              const SizedBox(height: 6),
              Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: onTap == null ? NV.faint : NV.text)),
            ]),
          ),
        ),
      ),
    );
  }
}

class _MenuRow extends StatelessWidget {
  const _MenuRow({super.key, required this.icon, required this.title, this.value, this.subtitle, required this.onTap});
  final IconData icon;
  final String title;
  final String? value;
  final String? subtitle;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
          child: Row(children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(color: chipFill(), borderRadius: BorderRadius.circular(10), border: Border.all(color: NV.glassBorder)),
              child: Icon(icon, size: 17, color: accentInk(chipFill())),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: NV.text)),
                if (subtitle != null) Text(subtitle!, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: NV.muted)),
              ]),
            ),
            if (value != null)
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 140),
                child: Text(value!, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13, color: NV.muted)),
              ),
            const SizedBox(width: 4),
            Icon(CupertinoIcons.chevron_right, size: 14, color: NV.muted),
          ]),
        ),
      );
}

/// What the "+" menu can ask the chat screen to do.
class ComposerActions {
  const ComposerActions({required this.insertText, required this.startMention});
  /// Insert at the cursor (snippets, `@url:` refs).
  final void Function(String text) insertText;
  /// Put "@" in the field and open the mention list.
  final VoidCallback startMention;
}

/// The "+" menu: upload sources always; the desktop controls only when the
/// PC serves the composer catalog.
Future<void> showComposerMenu(BuildContext context, RemoteController r, ComposerActions a) => showGlassSheet<void>(
      context,
      builder: (ctx) {
        final c = r.composer;
        void go(VoidCallback f) {
          Navigator.pop(ctx);
          f();
        }

        return SafeArea(
          top: false,
          bottom: false,
          child: SingleChildScrollView(
            key: const ValueKey('composer-menu'),
            padding: const EdgeInsets.only(bottom: 12),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              _SheetHead('komposer · ${r.desktop?.name ?? 'pc'}', 'Tambahkan'),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                child: Text('Lampirkan · maks 25 MB', style: NV.monoLabel(size: 9.5, color: NV.muted)),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 8, 14, 6),
                child: Row(children: [
                  _Tile(key: const ValueKey('attach-gallery'), icon: CupertinoIcons.photo_on_rectangle, label: 'Foto / Galeri',
                      onTap: () => go(() => attachFrom(context, r, AttachSource.gallery))),
                  const SizedBox(width: 8),
                  _Tile(key: const ValueKey('attach-camera'), icon: CupertinoIcons.camera, label: 'Kamera',
                      onTap: () => go(() => attachFrom(context, r, AttachSource.camera))),
                  const SizedBox(width: 8),
                  _Tile(key: const ValueKey('attach-file'), icon: CupertinoIcons.doc, label: 'File',
                      onTap: () => go(() => attachFrom(context, r, AttachSource.file))),
                  const SizedBox(width: 8),
                  _Tile(key: const ValueKey('attach-paste'), icon: CupertinoIcons.doc_on_clipboard, label: 'Tempel',
                      onTap: () => go(() => pasteClipboardImage(context, r))),
                ]),
              ),
              if (c != null) ...[
                if (c.skills.isNotEmpty)
                  _MenuRow(
                    key: const ValueKey('menu-skills'),
                    icon: CupertinoIcons.sparkles,
                    title: 'Skill',
                    subtitle: '${c.skills.length} skill di PC',
                    value: r.selectedSkills.isEmpty ? 'Tidak ada' : '${r.selectedSkills.length} dipilih',
                    onTap: () => go(() => showSkillPicker(context, r)),
                  ),
                if (c.hasModels)
                  _MenuRow(
                    key: const ValueKey('menu-model'),
                    icon: CupertinoIcons.cube,
                    title: 'Model',
                    value: shortModel(c.model),
                    onTap: () => go(() => showModelSheet(context, r)),
                  ),
                if (c.canSendEffort)
                  _MenuRow(
                    key: const ValueKey('menu-reasoning'),
                    icon: CupertinoIcons.lightbulb,
                    title: 'Penalaran',
                    value: c.effortLabel(r.reasoningEffort),
                    onTap: () => go(() => showReasoningSheet(context, r)),
                  ),
                _MenuRow(
                  key: const ValueKey('menu-mention'),
                  icon: CupertinoIcons.at,
                  title: 'Sebut file/folder di PC',
                  subtitle: 'Ketik @ di kolom pesan',
                  onTap: () => go(a.startMention),
                ),
                _MenuRow(
                  key: const ValueKey('menu-url'),
                  icon: CupertinoIcons.link,
                  title: 'Tautan (URL)',
                  onTap: () => go(() => showUrlDialog(context, a.insertText)),
                ),
                if (c.snippets.isNotEmpty)
                  _MenuRow(
                    key: const ValueKey('menu-snippets'),
                    icon: CupertinoIcons.text_bubble,
                    title: 'Cuplikan perintah',
                    subtitle: c.snippets.map((s) => s.label).join(' · '),
                    onTap: () => go(() => showSnippetsSheet(context, r, a.insertText)),
                  ),
              ],
            ]),
          ),
        );
      },
    );

class _SearchField extends StatelessWidget {
  const _SearchField({super.key, required this.hint, required this.onChanged});
  final String hint;
  final ValueChanged<String> onChanged;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: DecoratedBox(
          decoration: BoxDecoration(color: chipFill(), borderRadius: BorderRadius.circular(12), border: Border.all(color: NV.glassBorder)),
          child: TextField(
            onChanged: onChanged,
            style: TextStyle(fontSize: 14, color: NV.text),
            decoration: InputDecoration(
              hintText: hint,
              prefixIcon: Icon(CupertinoIcons.search, size: 16, color: NV.muted),
              border: InputBorder.none,
              enabledBorder: InputBorder.none,
              focusedBorder: InputBorder.none,
              filled: false,
              isDense: true,
              contentPadding: const EdgeInsets.symmetric(vertical: 11),
            ),
          ),
        ),
      );
}

/// Searchable multi-select of the PC's skills.
Future<void> showSkillPicker(BuildContext context, RemoteController r) => showGlassSheet<void>(
      context,
      tall: true,
      builder: (ctx) => _SkillPicker(r: r),
    );

class _SkillPicker extends StatefulWidget {
  const _SkillPicker({required this.r});
  final RemoteController r;
  @override
  State<_SkillPicker> createState() => _SkillPickerState();
}

class _SkillPickerState extends State<_SkillPicker> {
  String _q = '';
  late final Set<String> _picked = {...widget.r.selectedSkills};
  @override
  Widget build(BuildContext context) {
    final skills = widget.r.composer?.skills ?? const <ComposerSkill>[];
    final q = _q.toLowerCase();
    final shown = [for (final s in skills) if (q.isEmpty || s.name.toLowerCase().contains(q) || s.description.toLowerCase().contains(q)) s];
    final fill = prominentFill();
    return Column(key: const ValueKey('skill-picker'), mainAxisSize: MainAxisSize.min, children: [
      _SheetHead(
        'skill · ${skills.length} di PC',
        'Pilih skill',
        trailing: TextButton(
          key: const ValueKey('skill-done'),
          style: TextButton.styleFrom(backgroundColor: NV.red.withValues(alpha: 0.80), foregroundColor: inkOn(fill), shape: const StadiumBorder()),
          onPressed: () {
            widget.r.setSkills([for (final s in skills) if (_picked.contains(s.name)) s.name]);
            Navigator.pop(context);
          },
          child: Text(_picked.isEmpty ? 'Selesai' : 'Pakai ${_picked.length}', style: const TextStyle(fontWeight: FontWeight.w700)),
        ),
      ),
      _SearchField(key: const ValueKey('skill-search'), hint: 'Cari skill…', onChanged: (v) => setState(() => _q = v)),
      if (_picked.isNotEmpty)
        SizedBox(
          height: 38,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 3),
            children: [
              for (final s in _picked)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ComposerChip(label: '/$s', icon: CupertinoIcons.sparkles, selected: true, onRemove: () => setState(() => _picked.remove(s))),
                ),
            ],
          ),
        ),
      Flexible(
        child: shown.isEmpty
            ? Padding(padding: const EdgeInsets.all(24), child: Text('Tidak ada skill yang cocok', style: TextStyle(color: NV.muted)))
            : ListView.builder(
                shrinkWrap: true,
                padding: const EdgeInsets.only(bottom: 12),
                itemCount: shown.length,
                itemBuilder: (_, i) {
                  final s = shown[i];
                  final on = _picked.contains(s.name);
                  return InkWell(
                    key: ValueKey('skill-row-${s.name}'),
                    onTap: () => setState(() => on ? _picked.remove(s.name) : _picked.add(s.name)),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                      child: Row(children: [
                        Icon(on ? CupertinoIcons.checkmark_circle_fill : CupertinoIcons.circle, size: 20, color: on ? accentInk(chipFill()) : NV.muted),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text('/${s.name}', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: NV.text)),
                            if (s.description.isNotEmpty)
                              Text(s.description, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12.5, color: NV.muted, height: 1.3)),
                          ]),
                        ),
                      ]),
                    ),
                  );
                },
              ),
      ),
    ]);
  }
}

/// The PC's providers and models (same list as the desktop model pill).
Future<void> showModelSheet(BuildContext context, RemoteController r) => showGlassSheet<void>(
      context,
      tall: true,
      builder: (ctx) => _ModelSheet(r: r, outer: context),
    );

class _ModelSheet extends StatefulWidget {
  const _ModelSheet({required this.r, required this.outer});
  final RemoteController r;
  final BuildContext outer;
  @override
  State<_ModelSheet> createState() => _ModelSheetState();
}

class _ModelSheetState extends State<_ModelSheet> {
  String _q = '';
  @override
  Widget build(BuildContext context) {
    final c = widget.r.composer;
    final q = _q.toLowerCase();
    final rows = <Widget>[];
    for (final p in c?.providers ?? const <ComposerModelProvider>[]) {
      final models = [for (final m in p.models) if (q.isEmpty || m.toLowerCase().contains(q) || p.name.toLowerCase().contains(q)) m];
      if (models.isEmpty) continue;
      rows.add(Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
        child: Text(p.name, style: NV.monoLabel(size: 9.5, color: NV.muted)),
      ));
      for (final m in models) {
        final cur = p.slug == c!.provider && m == c.model;
        rows.add(InkWell(
          key: ValueKey('model-row-${p.slug}-$m'),
          onTap: () async {
            Navigator.pop(context);
            if (cur) return;
            final err = await widget.r.selectModel(p.slug, m);
            if (err != null && widget.outer.mounted) toast(widget.outer, err);
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: Row(children: [
              Expanded(child: Text(m, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 14.5, fontWeight: cur ? FontWeight.w700 : FontWeight.w500, color: NV.text))),
              if (cur) Icon(CupertinoIcons.checkmark_alt, size: 18, color: accentInk(chipFill())),
            ]),
          ),
        ));
      }
    }
    return Column(key: const ValueKey('model-sheet'), mainAxisSize: MainAxisSize.min, children: [
      _SheetHead('model · berlaku untuk PC', 'Pilih model'),
      _SearchField(key: const ValueKey('model-search'), hint: 'Cari model…', onChanged: (v) => setState(() => _q = v)),
      Flexible(child: ListView(shrinkWrap: true, padding: const EdgeInsets.only(bottom: 12), children: rows)),
    ]);
  }
}

/// Reasoning effort for the next prompts (Bawaan = the PC's default).
Future<void> showReasoningSheet(BuildContext context, RemoteController r) => showGlassSheet<void>(
      context,
      builder: (ctx) {
        final c = r.composer!;
        final levels = ['default', ...c.reasoningLevels];
        return SafeArea(
          top: false,
          bottom: false,
          child: SingleChildScrollView(
            key: const ValueKey('reasoning-sheet'),
            padding: const EdgeInsets.only(bottom: 12),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              _SheetHead('penalaran · per pesan', 'Usaha berpikir'),
              for (final l in levels)
                InkWell(
                  key: ValueKey('reasoning-$l'),
                  onTap: () {
                    r.setReasoningEffort(l);
                    Navigator.pop(ctx);
                  },
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
                    child: Row(children: [
                      Expanded(
                        child: Text(
                          l == 'default' ? 'Bawaan (${c.effortLabel(c.reasoningDefault)})' : c.effortLabel(l),
                          style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: NV.text),
                        ),
                      ),
                      if ((r.reasoningEffort ?? 'default') == l) Icon(CupertinoIcons.checkmark_alt, size: 18, color: accentInk(chipFill())),
                    ]),
                  ),
                ),
            ]),
          ),
        );
      },
    );

/// Desktop "+" → prompt snippets.
Future<void> showSnippetsSheet(BuildContext context, RemoteController r, void Function(String) insert) => showGlassSheet<void>(
      context,
      builder: (ctx) => SingleChildScrollView(
        key: const ValueKey('snippets-sheet'),
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          _SheetHead('cuplikan', 'Cuplikan perintah'),
          for (final s in r.composer?.snippets ?? const <ComposerSnippet>[])
            _MenuRow(
              key: ValueKey('snippet-${s.id}'),
              icon: CupertinoIcons.text_bubble,
              title: s.label,
              subtitle: s.description,
              onTap: () {
                Navigator.pop(ctx);
                insert(s.text);
              },
            ),
        ]),
      ),
    );

/// Desktop "+" → URL: inserts an `@url:` reference.
Future<void> showUrlDialog(BuildContext context, void Function(String) insert) async {
  final ctl = TextEditingController();
  String? err;
  final url = await showGlassSheet<String>(
    context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        void submit() {
          var v = ctl.text.trim();
          if (v.isNotEmpty && !v.contains('://')) v = 'https://$v';
          final u = Uri.tryParse(v);
          if (u == null || !(u.scheme == 'http' || u.scheme == 'https') || u.host.isEmpty) {
            set(() => err = 'Masukkan tautan http(s) yang valid');
            return;
          }
          Navigator.pop(ctx, v);
        }

        return Padding(
          key: const ValueKey('url-sheet'),
          padding: const EdgeInsets.only(bottom: 14),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            _SheetHead('referensi · @url', 'Tambahkan tautan'),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 0),
              child: DecoratedBox(
                decoration: BoxDecoration(color: chipFill(), borderRadius: BorderRadius.circular(12), border: Border.all(color: NV.glassBorder)),
                child: TextField(
                  key: const ValueKey('url-field'),
                  controller: ctl,
                  autofocus: true,
                  keyboardType: TextInputType.url,
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => submit(),
                  style: TextStyle(fontSize: 14, color: NV.text),
                  decoration: InputDecoration(
                    hintText: 'https://…',
                    border: InputBorder.none,
                    enabledBorder: InputBorder.none,
                    focusedBorder: InputBorder.none,
                    filled: false,
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                  ),
                ),
              ),
            ),
            if (err != null) Padding(padding: const EdgeInsets.fromLTRB(18, 6, 16, 0), child: Text(err!, style: TextStyle(fontSize: 12, color: NV.text))),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
              child: Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  key: const ValueKey('url-add'),
                  style: TextButton.styleFrom(backgroundColor: NV.red.withValues(alpha: 0.80), foregroundColor: inkOn(prominentFill()), shape: const StadiumBorder()),
                  onPressed: submit,
                  child: const Text('Tambahkan', style: TextStyle(fontWeight: FontWeight.w700)),
                ),
              ),
            ),
          ]),
        );
      },
    ),
  );
  if (url != null) insert('@url:$url ');
}
