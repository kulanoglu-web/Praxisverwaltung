package de.kulanoglu.praxisverwaltung
import android.app.*
import android.os.*
import android.graphics.*
import android.view.*
import android.widget.*
import java.text.SimpleDateFormat
import java.util.*

class InkView(ctx: android.content.Context): View(ctx) {
 private val paint=Paint().apply{color=Color.BLACK;strokeWidth=6f;style=Paint.Style.STROKE;strokeCap=Paint.Cap.ROUND;isAntiAlias=true}
 private val path=Path()
 override fun onDraw(c:Canvas){super.onDraw(c);c.drawColor(Color.WHITE);c.drawPath(path,paint)}
 override fun onTouchEvent(e:MotionEvent):Boolean { when(e.action){MotionEvent.ACTION_DOWN->path.moveTo(e.x,e.y);MotionEvent.ACTION_MOVE->path.lineTo(e.x,e.y)};invalidate();return true }
 fun clear(){path.reset();invalidate()}
}
class MainActivity: Activity() {
 private lateinit var clock:TextView; private var startMs=0L; private var running=false
 private val h=Handler(Looper.getMainLooper())
 private val tick=object:Runnable{override fun run(){clock.text="LIVE  "+SimpleDateFormat("HH:mm:ss",Locale.GERMANY).format(Date());h.postDelayed(this,250)}}
 override fun onCreate(b:Bundle?){super.onCreate(b)
  val root=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(24,24,24,24)}
  val title=TextView(this).apply{text="Praxisverwaltung";textSize=26f;setTypeface(null,1)}
  clock=TextView(this).apply{textSize=24f;gravity=Gravity.END}
  root.addView(title);root.addView(clock)
  val names=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL}
  val last=EditText(this).apply{hint="Nachname"}; val first=EditText(this).apply{hint="Vorname"}
  names.addView(last,LinearLayout.LayoutParams(0,-2,1f));names.addView(first,LinearLayout.LayoutParams(0,-2,1f));root.addView(names)
  val date=EditText(this).apply{hint="Datum";setText(SimpleDateFormat("dd.MM.yyyy",Locale.GERMANY).format(Date()))}
  val begin=EditText(this).apply{hint="Beginn (manuell)"}; val end=EditText(this).apply{hint="Ende"}
  root.addView(date);root.addView(begin);root.addView(end)
  val note=EditText(this).apply{hint="Sitzungsnotiz";gravity=Gravity.TOP;minLines=4};root.addView(note)
  val ink=InkView(this);root.addView(ink,LinearLayout.LayoutParams(-1,0,1f))
  val buttons=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL}
  val start=Button(this).apply{text="Start";setOnClickListener{startMs=System.currentTimeMillis();running=true}}
  val stop=Button(this).apply{text="Ende";setOnClickListener{running=false;end.setText(SimpleDateFormat("HH:mm",Locale.GERMANY).format(Date()))}}
  val clear=Button(this).apply{text="Stift löschen";setOnClickListener{ink.clear()}}
  buttons.addView(start);buttons.addView(stop);buttons.addView(clear);root.addView(buttons)
  setContentView(root);h.post(tick)
 }
 override fun onDestroy(){h.removeCallbacks(tick);super.onDestroy()}
}
