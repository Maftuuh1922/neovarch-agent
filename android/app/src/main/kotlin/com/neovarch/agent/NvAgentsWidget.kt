package com.neovarch.agent

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.RemoteViews
import android.widget.RemoteViewsService

/**
 * "Neovarch · Agen" (4x4, resizable): every agent with its coat avatar
 * (initial + status dot, agent-identity-spec), name, current task and status
 * pill; a row opens that agent's sheet (`nv_route=agent:<id>`), "Kasih tugas"
 * opens Tugas baru. Android 12+: RemoteCollectionItems (no service);
 * older: the same rows through [NvAgentsService].
 */
class NvAgentsWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        update(context, manager, ids)
    }

    override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, newOptions: Bundle?) {
        update(context, manager, intArrayOf(id))
    }

    companion object {
        fun refresh(context: Context) {
            val m = AppWidgetManager.getInstance(context)
            update(context, m, m.getAppWidgetIds(ComponentName(context, NvAgentsWidget::class.java)))
        }

        private fun update(context: Context, m: AppWidgetManager, ids: IntArray) {
            if (ids.isEmpty()) return
            for (id in ids) m.updateAppWidget(id, views(context, id))
            @Suppress("DEPRECATION")
            if (Build.VERSION.SDK_INT < 31) m.notifyAppWidgetViewDataChanged(ids, R.id.nva_list)
        }

        fun views(context: Context, widgetId: Int, s: NvWidgetState? = NvWidgets.state(context)): RemoteViews {
            val st = s ?: NvWidgetState.EMPTY
            val pal = NvWidgets.Palette(context)
            val v = RemoteViews(context.packageName, R.layout.nv_agents_widget)
            v.setTextViewText(R.id.nva_sub, NvWidgetText.agentsSub(st))
            NvWidgets.tint(context, v, R.id.nva_assign_bg, NvWidgets.accent(pal, s))
            NvWidgets.tint(context, v, R.id.nva_empty_wash, NvWidgets.accent(pal, s))
            NvWidgets.tint(context, v, R.id.nva_empty_ic, NvWidgets.accent(pal, s))
            v.setOnClickPendingIntent(android.R.id.background, NvWidgets.route(context, if (st.paired) "kantor" else "connect", 60))

            if (!st.paired) {
                v.setTextViewText(R.id.nva_assign_label, NvLocale.str(context, R.string.nv_connect_pc))
                v.setOnClickPendingIntent(R.id.nva_assign, NvWidgets.route(context, "connect", 61))
                v.setTextViewText(R.id.nva_empty_title, NvLocale.str(context, R.string.nv_not_connected))
                v.setTextViewText(R.id.nva_empty_sub, NvLocale.str(context, R.string.nva_pair_hint))
                v.setImageViewResource(R.id.nva_empty_ic, R.drawable.nvw_ic_link)
            } else {
                v.setTextViewText(R.id.nva_assign_label, NvLocale.str(context, R.string.nva_assign))
                v.setOnClickPendingIntent(R.id.nva_assign, NvWidgets.route(context, "newtask", 62))
                v.setTextViewText(R.id.nva_empty_title, NvLocale.str(context, if (st.connected) R.string.nva_no_agents else R.string.nva_pc_offline))
                v.setTextViewText(R.id.nva_empty_sub, NvLocale.str(context, if (st.connected) R.string.nva_no_agents_sub else R.string.nva_offline_sub))
                v.setImageViewResource(R.id.nva_empty_ic, if (st.connected) R.drawable.nvw_ic_agents else R.drawable.nvw_ic_pc)
            }

            val agents = if (st.paired) st.agents else emptyList()
            v.setPendingIntentTemplate(R.id.nva_list, NvWidgets.rowTemplate(context, 63))
            v.setEmptyView(R.id.nva_list, R.id.nva_empty)
            if (Build.VERSION.SDK_INT >= 31) {
                val b = RemoteViews.RemoteCollectionItems.Builder().setHasStableIds(true).setViewTypeCount(1)
                for (a in agents) b.addItem(a.id.hashCode().toLong(), row(context, pal, a))
                v.setRemoteAdapter(R.id.nva_list, b.build())
            } else {
                val intent = Intent(context, NvAgentsService::class.java)
                    .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId)
                // unique per widget, or the system reuses one factory for all
                intent.data = Uri.parse(intent.toUri(Intent.URI_INTENT_SCHEME))
                @Suppress("DEPRECATION")
                v.setRemoteAdapter(R.id.nva_list, intent)
            }
            // a list with no agents: the empty view (setEmptyView) shows instead
            v.setViewVisibility(R.id.nva_empty, if (agents.isEmpty()) View.VISIBLE else View.GONE)
            return v
        }

        /** One agent row (shared by both collection paths). */
        fun row(context: Context, pal: NvWidgets.Palette, a: NvWidgetAgent): RemoteViews {
            val r = RemoteViews(context.packageName, R.layout.nv_agents_row)
            NvWidgets.tint(r, R.id.nva_av, a.coat)
            r.setTextViewText(R.id.nva_init, a.initial)
            val sc = NvWidgets.statusColor(pal, a.status)
            NvWidgets.tint(context, r, R.id.nva_dot, sc)
            r.setTextViewText(R.id.nva_name, a.name)
            r.setTextViewText(R.id.nva_task, NvWidgetText.agentTask(a))
            r.setTextViewText(R.id.nva_status, NvWidgetText.statusLabel(a.status))
            NvWidgets.colorInt(context, r, R.id.nva_status, "setTextColor", sc)
            r.setOnClickFillInIntent(R.id.nva_row, Intent().putExtra(NvWidgets.EXTRA_ROUTE, "agent:" + a.id))
            return r
        }
    }
}

/** API < 31: the agent rows of [NvAgentsWidget] as a RemoteViewsService. */
class NvAgentsService : RemoteViewsService() {
    override fun onGetViewFactory(intent: Intent): RemoteViewsFactory = Factory(applicationContext)

    private class Factory(private val context: Context) : RemoteViewsFactory {
        private var agents: List<NvWidgetAgent> = emptyList()
        private var pal: NvWidgets.Palette? = null

        override fun onCreate() {}
        override fun onDataSetChanged() {
            val st = NvWidgets.state(context)
            agents = if (st?.paired == true) st.agents else emptyList()
            pal = NvWidgets.Palette(context)
        }
        override fun onDestroy() { agents = emptyList() }
        override fun getCount() = agents.size
        override fun getViewAt(position: Int): RemoteViews? {
            val a = agents.getOrNull(position) ?: return null
            return NvAgentsWidget.row(context, pal ?: NvWidgets.Palette(context).also { pal = it }, a)
        }
        override fun getLoadingView(): RemoteViews? = null
        override fun getViewTypeCount() = 1
        override fun getItemId(position: Int) = agents.getOrNull(position)?.id?.hashCode()?.toLong() ?: position.toLong()
        override fun hasStableIds() = true
    }
}
