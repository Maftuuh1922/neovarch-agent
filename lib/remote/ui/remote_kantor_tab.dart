// The Crew tab (formerly Kantor) holds three views behind a glass segmented
// control: "Crew | Tugas | Lanjutan". Crew is the main agent's team of agents
// (goal → proposal → approval → pixel room); Tugas is the PC's task board;
// Lanjutan edits a crew by hand and keeps the old Kantor and Perusahaan views
// (Perusahaan only when the paired core has the `company.*` RPCs).
// Segmented control only, no swipe: the Tugas lane strip scrolls horizontally.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../ui/widgets/motion.dart' show TabFade;

import '../l10n/strings.dart';
import '../remote_controller.dart';
import 'nv_widgets.dart';
import 'remote_crew_screen.dart';
import 'remote_tasks_screen.dart';

/// Segment indices inside the Crew tab.
const kantorSegCrew = 0, kantorSegTasks = 1, kantorSegAdvanced = 2;

/// Older names kept for routes and callers: the Kantor view is now Crew, and
/// Perusahaan lives under Lanjutan.
const kantorSegOffice = kantorSegCrew, kantorSegCompany = kantorSegAdvanced;

/// Web preview / tests: which segment the Crew tab opens on.
int previewKantorSegment = kantorSegCrew;

class RemoteKantorTab extends ConsumerWidget {
  const RemoteKantorTab({super.key, required this.segment, required this.onSegment, required this.onOpenChat, required this.onOpenApprovals});
  final int segment;
  final ValueChanged<int> onSegment;
  final VoidCallback onOpenChat;
  final VoidCallback onOpenApprovals;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final top = MediaQuery.paddingOf(context).top;
    final company = ref.watch(remoteProvider.select((r) => r.companySupported)) != false;
    final segment = this.segment.clamp(kantorSegCrew, kantorSegAdvanced);
    return Column(children: [
      Padding(
        padding: EdgeInsets.fromLTRB(16, top + 10, 16, 0),
        child: NvGlassSegmented(
          key: const ValueKey('kantor-segments'),
          labels: [tr('Crew'), tr('Tugas'), tr('Lanjutan')],
          index: segment,
          onChanged: onSegment,
        ),
      ),
      Expanded(
        child: MediaQuery.removePadding(
          context: context,
          removeTop: true,
          child: IndexedStack(index: segment, children: [
            TabFade(active: segment == kantorSegCrew, child: RemoteCrewScreen(onOpenAdvanced: () => onSegment(kantorSegAdvanced))),
            TabFade(active: segment == kantorSegTasks, child: const RemoteTasksScreen()),
            TabFade(
              active: segment == kantorSegAdvanced,
              child: RemoteCrewAdvanced(onOpenChat: onOpenChat, onOpenApprovals: onOpenApprovals, companySupported: company),
            ),
          ]),
        ),
      ),
    ]);
  }
}
