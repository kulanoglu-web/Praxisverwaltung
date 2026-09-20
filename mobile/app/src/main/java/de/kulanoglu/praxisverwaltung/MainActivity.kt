package de.kulanoglu.praxisverwaltung
import android.app.*
import android.os.*
import android.graphics.*
import android.view.*
import android.widget.*
import java.text.SimpleDateFormat
import java.util.*
import android.content.Context
import org.json.JSONObject
import java.io.File

class InkView(ctx: android.content.Context): View(ctx) {
 private val paint=Paint().apply{color=Color.BLACK;strokeWidth=6f;style=Paint.Style.STROKE;strokeCap=Paint.Cap.ROUND;isAntiAlias=true}
 private val path=Path()
 override fun onDraw(c:Canvas){super.onDraw(c);c.drawColor(Color.WHITE);c.drawPath(path,paint)}
 override fun onTouchEvent(e:MotionEvent):Boolean { when(e.action){MotionEvent.ACTION_DOWN->path.moveTo(e.x,e.y);MotionEvent.ACTION_MOVE->path.lineTo(e.x,e.y)};invalidate();return true }
 fun clear(){path.reset();invalidate()}
}
class MainActivity: Activity() {
 private lateinit var clock:TextView; private lateinit var timer:TextView; private var startMs=0L; private var elapsed=0L; private var running=false
 private val h=Handler(Looper.getMainLooper())
 private val tick=object:Runnable{override fun run(){
  clock.text="LIVE  "+SimpleDateFormat("HH:mm:ss",Locale.GERMANY).format(Date())
  val ms=elapsed + if(running) System.currentTimeMillis()-startMs else 0L; val sec=ms/1000
  timer.text=String.format(Locale.GERMANY,"%02d:%02d:%02d",sec/3600,(sec%3600)/60,sec%60); h.postDelayed(this,250)}}
 override fun onCreate(b:Bundle?){super.onCreate(b)
  val root=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(24,24,24,24)}
  val title=TextView(this).apply{text="Praxisverwaltung";textSize=26f;setTypeface(null,1)}
  clock=TextView(this).apply{textSize=24f;gravity=Gravity.END}
  timer=TextView(this).apply{textSize=30f;gravity=Gravity.CENTER;text="00:00:00"}
  root.addView(title);root.addView(clock);root.addView(timer)
  val names=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL}
  val last=EditText(this).apply{hint="Nachname"}; val first=EditText(this).apply{hint="Vorname"}
  names.addView(last,LinearLayout.LayoutParams(0,-2,1f));names.addView(first,LinearLayout.LayoutParams(0,-2,1f));root.addView(names)
  val date=EditText(this).apply{hint="Datum";setText(SimpleDateFormat("dd.MM.yyyy",Locale.GERMANY).format(Date()))}
  val begin=EditText(this).apply{hint="Beginn (manuell)"}; val end=EditText(this).apply{hint="Ende"}
  root.addView(date);root.addView(begin);root.addView(end)
  val note=EditText(this).apply{hint="Sitzungsnotiz";gravity=Gravity.TOP;minLines=4};root.addView(note)
  val ink=InkView(this);root.addView(ink,LinearLayout.LayoutParams(-1,0,1f))
  val buttons=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL}
  val start=Button(this).apply{text="Start";setOnClickListener{if(!running){startMs=System.currentTimeMillis();running=true}}}
  val pause=Button(this).apply{text="Pause";setOnClickListener{if(running){elapsed+=System.currentTimeMillis()-startMs;running=false}else{startMs=System.currentTimeMillis();running=true}}}
  val stop=Button(this).apply{text="Ende";setOnClickListener{if(running)elapsed+=System.currentTimeMillis()-startMs;running=false;end.setText(SimpleDateFormat("HH:mm",Locale.GERMANY).format(Date()))}}
  val clear=Button(this).apply{text="Stift löschen";setOnClickListener{ink.clear()}}
  buttons.addView(start);buttons.addView(pause);buttons.addView(stop);buttons.addView(clear);root.addView(buttons)
  val save=Button(this).apply{text="Sitzung lokal speichern";setOnClickListener{
    val o=JSONObject();o.put("last",last.text.toString());o.put("first",first.text.toString());o.put("date",date.text.toString());o.put("begin",begin.text.toString());o.put("end",end.text.toString());o.put("seconds",elapsed/1000);o.put("notes",note.text.toString())
    val dir=File(filesDir,"sessions");dir.mkdirs();File(dir,"session_"+System.currentTimeMillis()+".json").writeText(o.toString(2))
    Toast.makeText(this,"Sitzung lokal gespeichert",Toast.LENGTH_SHORT).show()
  }};root.addView(save)
  setContentView(root);h.post(tick)
 }
 override fun onDestroy(){h.removeCallbacks(tick);super.onDestroy()}
}
