Attribute VB_Name = "Module1"
'   Solar Collection, PTC, Dynamic Model and Model-Based Control
'   Three Collection Lines and one common pump
'   Primary exit T controller (PI) sends a set point to the mid-line T secondary controller (GMC-SS) which
'       sends a flow set point to the tertiary flow controller (PMBC) which sends the signal to the valve.
'   Pump speed is adjusted to keep max open valve nearly fully open, to minimize parasitic energy consumption.
'       Options permit heuristic incremental control or PI control of pump speed.
'   In all it is a 4-level cascade.
'   Options permit central difference or backward difference in the line T model.  I don't see any real difference, but
'       backward difference is simpler and permits a larger dt for stability.
'   Options permit SPC or FOF filter on the noisy F measurement.  But which seems to have no real impact on the controlled process.
'
'   How to prevent control interaction?  Cascade does it, Flow control changes the upset F long before it can affect exit T.
'   Density drops about 15% from inlet 300C to exit 400C.  So F increases along the pipe.  I switched Process T modeling to M-dot instead of F,
'       but kept constant dens F modeling in the T model.  It does not make a noticeable difference for the controlled process.
'   Density, Cp, conductivity, and viscosity are all T dependent.  So hinside is a function of T, but these have very little net
'       impact on hinside.  Although true for the collection pipe and inside the boiler where fluid T changes, in all the other piping T is constant.
'
'   If used, Model-Estimated optical efficiency needs strong filtering.  GMC Control uses optical efficiency, if it changes, then GMC
'       changes the valve, which changes F, which changes the model-estimated optical efficiency.  The model-estimated efficiency
'       is a SS model not a dynamic model, so it things change, the SS model does not match the process.  So, there are two issues
'       requiring slow model parameter adjustment. However, even with strong filtering the model-estimated optical efficiency tracks
'       the actual very well. And GMC does not really need the adjustment, because it uses the PI integral.
'
'
'   R. Russell Rhinehart
'   2026-04-21
'
'
'           MODIFICATIONS  TO-DO
'
'   Central difference seems to be unstable.  Why?
'   Scale-up to 5 pumps and 15 lines and operation of n of N pumps.
'   Calculate the thermal energy delivered less the pump consumption.
'   Compare Solar energy possible over the day with e=1, ha=0, and no pump losses,
'       to the thermal energy collected and delivered to the boiler with optical efficiency and ambient losses,
'       to energy generated (to the Boiler times Carnot Efficiency),
'       and to that generated less the pump parasitic consumption.
'   Organize the code for sharing - more comment lines, remove deadwood, group Dim
'
'           LOW PRIORITY
'
'   Use the mechanistic model for DNI, not the simple approximation.  Approximation is very good, but not rigorous.
'      May be more instructive for a learner, but not really relevant to plant modeling, control or optimization.
'
'           UNITS
'   Mdot [kg/s]
'   F [m3/s]
'   rho [kg/m3]
'   Cp [kJ/(kg K)]
'   mu [Pa s] = [N/(m2 s)]
'   k [kJ/(s m K)]
'   DNI [kJ/(m2 K)]
'   W [m]
'   L [m]
'   t [s]
'   h [kJ/(m2 s K)]
'   Dispersion [kJ/(m s K)]
'   gc [kg m /(N s2)]
'
'
'
Dim Irad, MirrorWidth, R, L, dens, Cp, Tamb, eff, hamb, volfract, dz, dt, simtime, i, N, Velement
Dim Elambda, Esigmad, eff1(3), Edrift(3)
Dim Tlambda, Tsigmad, Tdrift
Dim Iraddrift, tauIraddrift, rangeIraddrift, Iradlambda, Iradsigmad, Irad1
Dim adrift(3), tauadrift, rangeadrift, alambda, asigmad, flowa1(3)
Dim Fbase, effbase, effold, cinterval, controlcount
Dim T1SP, T1bias(3), T2SP(3), T2bias(3)
Dim TSPBias(3), GMCm(3), GMCbias(3), Fdesired(3), T2SPBias(3)
Dim effmeas, effmeasold, Told, Fold, acterrold, tauw
Dim deltaIrad, Iradmeas, Iradold, Iraddrop
Dim bias(3), Tbias(3)
Dim Tb(3, 500), Ta(3, 500), Tin, Tin1, PipeT(3, 500)
Dim T2model(3)
Dim ProcessA, ProcessB, ProcessC, ProcessD
Dim ISE1(3), ISE2(3), nISE1, nISE2
Dim GMCGain
Dim Iterm(3), T1PIGain, T1PITau
Dim linedp(3), dPpump, valvexm(3), spumps, spumpsold
Dim dPLmeas(3), Fmeas(3), Fm(3), fofxm, Fpmm(3)
Dim hin
Dim MBCtauw
Dim midTerror(3), T2meas(3), T1meas(3)
Dim DNI, simtimeh
Dim Cv, G, valveR, Flowa, Flowb, flowaest(3), flowbest
Dim valvetau, fofxdesired
Dim iout, PEnergy, TotalEnergy
Dim Fmeasnoise
Dim Re, minRe, maxRe, Theta, maxTheta, minTheta
Dim valvex(3), valvextarg(3), valvexold(3)
Dim fofx, F(3), Ftotal
Dim dPSys, spumpstarg, pumptau
Dim noiseFiltTau, noiselambda, Fmeasfilt(3)
Dim FlowaFiltTau, Flowalambda
Dim FpmmFiltTau, Fpmmlambda
Dim Dispersion
Dim effdrop(3)
Dim interval_count As Integer
Dim method As String
Dim pumpintegral, PumpPIGain, PumpPITau
Dim epsilonest(3), Tinmeas
Dim SPCN(3), SPCX, SPCV(3), SPCXOLD(3), CUSUM(3)
Dim Mdot(3), Mdottotal, EvalCount
Dim pipeTlambda
Dim Tmixed, HighTViol, LowTViol, PumpTravel, ValveTravel
Dim itrial
Dim outinterval, subinterval_count
'
'
Sub Main()
    
    Sheets("Analysis").Select
    Range("I7:Q156").Select
    Selection.ClearContents
    Range("F21").Select
    Sheets("Main").Select
    Range("J6").Select
    
'    Application.ScreenUpdating = False

'    Application.Calculation = xlManual

    For itrial = 1 To 100   '100
        
        start_time = Timer
    
        Call Initialize
        
        simtimeh = 8
        Cells(8, 2) = simtimeh
        
        outinterval = Int(8 * 3600 / 350 / Cells(1, 12))            '350 outputs in 8 hours
        outskip = outinterval
        
        For i = 1 To 300000
            Call Events
            simtime = simtime + dt  'sec
            simtimeh = 8 + simtime / 3600       'hours
            If simtimeh > 16 Then Exit For
            Call Process
            cinterval = cinterval + dt
            If cinterval >= Cells(1, 12) Then
                Call Measure
                Call Estimate_Coefficients
                If Cells(12, 9) = "Y" Then
                    Call T1Control
                    Call T2Control
                    Call FControl
                    If Cells(5, 2) = "Y" Then Call PumpControl
                End If
                Call Evaluate
                Outputskip = Outputskip + 1
                If Outputskip > outinterval Then
                    Call Output
                    Outputskip = 0
                End If
                cinterval = 0
            End If
        Next i
        
        Cells(2, 15) = simtime
        Cells(9, 2) = simtimeh
        Call Tdistribution
        
        Cells(9, 21) = (Timer - start_time) / 60
        
        Sheets("Analysis").Cells(itrial + 6, 9) = itrial
        Sheets("Analysis").Cells(itrial + 6, 10) = TotalEnergy       'Thermal energy collected
        Sheets("Analysis").Cells(itrial + 6, 11) = Cells(10, 2)      'pump parasitic energy
        Sheets("Analysis").Cells(itrial + 6, 12) = Cells(2, 24)      'pump travel
        Sheets("Analysis").Cells(itrial + 6, 13) = Cells(2, 27)      'valve travel
        Sheets("Analysis").Cells(itrial + 6, 14) = Cells(1, 24)      'Hi exit T accumulation
        Sheets("Analysis").Cells(itrial + 6, 15) = Cells(1, 27)      'Low mix T accumulation
        Sheets("Analysis").Cells(itrial + 6, 16) = Cells(10, 87)     'sigma on Mixed T
        Sheets("Analysis").Cells(itrial + 6, 17) = Cells(10, 86)     'sigma on Observed exit T
        
    Next itrial
    
'    Application.ScreenUpdating = True
    
    Sheets("Main").Select
    Range("J6").Select

'    Application.Calculation = xlAutomatic

    Call Macro1

End Sub
'
'
Sub PumpControl()

'    Convert this to a PI control keeping the most open valve to 0.95?

    maxvalvexm = 0
    For ValveN = 1 To 3
        If valvexm(ValveN) > maxvalvexm Then maxvalvexm = valvexm(ValveN)
    Next ValveN
    
    '   Heuristic
'    If maxvalvexm > 0.95 Then spumpstarg = spumpstarg + dt * 0.0004
'    If maxvalvexm < 0.9 Then spumpstarg = spumpstarg - dt * 0.0004

    '   PI
    valvexSP = 0.9
    valvexerr = -(valvexSP - maxvalvexm)
    If valvexerr > 0 Then
        pumppropor = 5 * PumpPIGain * valvexerr
    Else
        pumppropor = PumpPIGain * valvexerr
    End If
    pumpintegral = pumpintegral + dt * pumppropor / PumpPITau
    spumpstarg = pumppropor + pumpintegral
    
    '   Override
    If spumpstarg > 1 Then spumpstarg = 1
    If spumpstarg < 0.3 Then spumpstarg = 0.3

End Sub
'
'
Sub Estimate_Coefficients()
'   Use data to estimate model coefficient values

    sumF = 0
    For LineN = 1 To 3
        If Fmeasfilt(LineN) > 0 Then
            flowaest(LineN) = Flowalambda * dPLmeas(LineN) / (Fmeas(LineN)) ^ 2 + (1 - Flowalambda) * flowaest(LineN)
        End If
        
        'Filter approach to estimate epsilon
'        epsilonest(LineN) = 0.005 * (T1meas(LineN) - T2meas(LineN)) * Fmeasfilt(LineN) * rhocp((T1meas(LineN) + T2meas(LineN)) / 2) / (Iradmeas * MirrorWidth * L / 2) + 0.995 * epsilonest(LineN) 'optical efficiency
        'The IMPOL approach, but the GMC law does not use pmm.  There is no model estimate of T2.  Could insert it here, then use IMPOL.
        T1ssm = T2meas(LineN) + Iradmeas * epsilonest(LineN) * MirrorWidth * (L / 2) / (Fmeasfilt(LineN) * rhocp((T1meas(LineN) + T2meas(LineN)) / 2))
        T1pmm = T1meas(LineN) - T1ssm
        epsilonest(LineN) = epsilonest(LineN) + (cinterval / 400) * T1pmm * Fmeasfilt(LineN) * rhocp((T1meas(LineN) + T2meas(LineN)) / 2) / (Iradmeas * MirrorWidth * (L / 2))
            
        sumF = sumF + Fmeasfilt(LineN)
    Next LineN
    flowbest = (Plineexit - Preturn) / (sumF) ^ 2   'flowb coefficient (boiler and header system)
    
End Sub
'
'
Sub Measure()   '

    Iradmeas = 0.95 * Irad1      'to create error from a measured Irradiance value
    
'    effmeas = 0.95 * eff        'to create error from the nominal value

    Tinmeas = Tin
    
    For LineN = 1 To 3
        Fmeas(LineN) = 0.95 * F(LineN)         '5% calibration error
        Fmeas(LineN) = Fmeas(LineN) * (1 + Fmeasnoise * Sqr(-2 * Log(1 - Rnd)) * Sin(2 * 3.14159 * Rnd))      'with noise
        
        If Cells(7, 2) = "FOF" Then     'FOF to temper noise
            Fmeasfilt(LineN) = noiselambda * Fmeas(LineN) + (1 - noiselambda) * Fmeasfilt(LineN)                    'Fitered
        Else                            'SPC Filter
            SPCN(LineN) = SPCN(LineN) + 1
            SPCX = Fmeas(LineN)
            SPCV(LineN) = 0.05 * (SPCX - SPCXOLD(LineN)) ^ 2 + 0.9 * SPCV(LineN)
            SPCXOLD(LineN) = SCPX
            CUSUM(LineN) = CUSUM(LineN) + SPCX - Fmeasfilt(LineN)
            If (Abs(CUSUM(LineN)) > TRIGGER * Sqr(SPCV(LineN) * SPCN(LineN))) Then
                Fmeasfilt(LineN) = Fmeasfilt(LineN) + CUSUM(LineN) / SPCN(LineN)
                SPCN(LineN) = 0
                CUSUM(LineN) = 0
            End If
        End If
        
        dPLmeas(LineN) = 1.05 * (flowa1(LineN)) * (F(LineN)) ^ 2        '1.05 to create mismatch from true values
        
        T2meas(LineN) = Ta(LineN, Int(N / 2))       'true value
        T1meas(LineN) = Ta(LineN, N)
    Next LineN
    
End Sub
'
'
Sub T1Control()
    '   Primary T controller, PI
    
    For LineN = 1 To 3
        acterr = T1SP - Ta(LineN, N)
        Pterm = T1PIGain * acterr
        Iterm(LineN) = Iterm(LineN) + cinterval * T1PIGain * acterr / T1PITau
        T2SP(LineN) = Tin + (T1SP - Tin) / 2 + Pterm + Iterm(LineN)   'assumes that T2-Tin is half of Tsp-Tin
        
        '   Override
        If T2SP(LineN) > 365 Then
            T2SP(LineN) = 365
            Iterm(LineN) = T2SP(LineN) - Tin - (T1SP - Tin) / 2 - Pterm
        End If
        If T2SP(LineN) < 335 Then
            T2SP(LineN) = 335
            Iterm(LineN) = T2SP(LineN) - Tin - (T1SP - Tin) / 2 - Pterm
        End If
    Next LineN
    
End Sub
'
'
Sub T2Control()

    'GMC control
    'need to add MAN-AUTO transfer

    controlcount = controlcount + 1

    Call T2modelSub

    For LineN = 1 To 3
    
        '   GMC SS control with erf
        If Cells(12, 9) = "Y" Then         'AUTO
            '   This is the erf feedback signal
            T2SPBias(LineN) = Tin + (Iradmeas * MirrorWidth * epsilonest(LineN) * (L / 2)) / (dens * Cp * Fmeasfilt(LineN))
            GMCm(LineN) = T2SPBias(LineN) - T2SP(LineN)
            midTerror(LineN) = (T2SP(LineN) - T2meas(LineN))
            Pterm = GMCGain * midTerror(LineN)
            GMClam = 1 - Exp(-cinterval / tauw)
            GMCbias(LineN) = GMClam * GMCm(LineN) + (1 - GMClam) * GMCbias(LineN)
            GMCm(LineN) = Pterm + GMCbias(LineN)
            T2SPBias(LineN) = T2SP(LineN) + GMCm(LineN)
            Fdesired(LineN) = (Iradmeas * MirrorWidth * epsilonest(LineN) * (L / 2)) / (dens * Cp * (T2SPBias(LineN) - Tin))
        Else        'MAN
            GMCbias(LineN) = T2model(LineN) - Ta(LineN, Int(N / 2))
            GMCm(LineN) = 0
        End If
        
        'Override GMC T master, for excessive flow rates
        If Fdesired(LineN) > 0.01 Then Fdesired(LineN) = 0.01
        If Fdesired(LineN) < 0.001 Then Fdesired(LineN) = 0.001
        T2SPBias(LineN) = Tin + (Iradmeas * MirrorWidth * epsilonest(LineN) * (L / 2)) / (dens * Cp * Fdesired(LineN))
        GMCm(LineN) = T2SPBias(LineN) - T2SP(LineN)

    Next LineN
    
End Sub
'
'
Sub FControl()

    '   Flow Control - simple MBC - Valve position to get flow rate
    Call FModel
    If Cells(12, 9) = "Y" Then
        
        For ValveN = 1 To 3
'            Fpmm(valveN) = Fmeas(valveN) - Fm(valveN)
            Fpmm(ValveN) = Fpmmlambda * (Fmeasfilt(ValveN) - Fm(ValveN)) + (1 - Fpmmlambda) * Fpmm(ValveN)
            Fdesired(ValveN) = (Fdesired(ValveN) - Fpmm(ValveN))
            '   Valve to flow rate
            If (dPpump / Fdesired(ValveN) ^ 2 - flowaest(ValveN) - 9 * Flowb) > 0 Then
                fofxdesired = Sqr((G * 1) / (Cv ^ 2) / (dPpump / Fdesired(ValveN) ^ 2 - flowaest(ValveN) - 9 * Flowb))
            Else
                fofxdesired = 1
            End If
            valvexSP = 1 + Log(fofxdesired) / Log(50)     'SS target x
            valvextarg(ValveN) = valvetau / MBCtauw * (valvexSP - valvexm(ValveN)) + valvexm(ValveN)  'to push for faster change
            '     Override simple MBC secondary
            If valvextarg(ValveN) > 1 Then valvextarg(ValveN) = 1       'limits
            If valvextarg(ValveN) < 0.1 Then valvextarg(ValveN) = 0.1
        
        Next ValveN
    End If

End Sub
'
'
Sub T2modelSub()

    '   Steady State temperature Model - no ambient loss, no dispersion, uniform over collection pipe
    For LineN = 1 To 3
        T2model(LineN) = Tin + (Iradmeas * MirrorWidth * epsilonest(LineN) * (L / 2)) / (Fmeasfilt(LineN) * dens * Cp)
    Next LineN
    
End Sub
'
'
Sub FModel()
    
    '   Flow rate model
    For LineN = 1 To 3
        valvexm(LineN) = Exp(-cinterval / valvetau) * valvextarg(LineN) + (1 - Exp(-cinterval / valvetau)) * valvexm(LineN)
        If valvexm(LineN) > 1 Then valvexm(LineN) = 1
        If valvexm(LineN) < 0.1 Then valvexm(LineN) = 0.1
        fofxm = valveR ^ (valvexm(LineN) - 1)
        Fm(LineN) = Cv * fofxm * Sqr(dPpump / (G * 1 + (flowaest(LineN) + 9 * Flowb) * (Cv * fofxm) ^ 2))   'flow rate m^3 per hour
    Next LineN
    
End Sub
'
'
Sub Events()

'   An empirical model based on a first principles model of how DNI changes with sun angle - Page 72
'    DNI = (1000 - 2 * (Abs(12 - simtimeh)) ^ 3.8) / 1000
    DNI = (950 - 2 * (Abs(12 - simtimeh)) ^ 3.8) / 1000
  
    eee = Round(simtimeh, 2)
    
        '   Valves in Manual
    If Cells(7, 9) = "Y" Then
        
        If eee = 8.5 Then
            valvextarg(1) = 0.1
        End If
        If eee = 9.5 Then
            valvextarg(1) = 0.95
        End If
        If eee = 10.5 Then
            valvextarg(2) = 0.1
        End If
        If eee = 11.5 Then
            valvextarg(2) = 0.95
        End If
        If eee = 12.5 Then
            valvextarg(3) = 0.1
        End If
        If eee = 13.5 Then
            valvextarg(3) = 0.95
        End If
    End If
    
    If Cells(9, 9) = "Y" Then
        '   optical efficiency
        If eee = 8.5 Then
            effdrop(1) = 0.2
        End If
        If eee = 9.5 Then
            effdrop(1) = 0
        End If
        If eee = 10.5 Then
            effdrop(2) = 0.2
        End If
        If eee = 11.5 Then
            effdrop(2) = 0
        End If
        If eee = 12.5 Then
            effdrop(3) = 0.2
        End If
        If eee = 13.5 Then
            effdrop(3) = 0
        End If
    End If
    
    If Cells(8, 9) = "Y" Then
        'T1 Set Point
        If eee = 10.5 Then
            T1SP = 380
        End If
        If eee = 11.5 Then
            T1SP = 395
        End If
    End If
    
    If Cells(7, 12) = "Y" Then
        '   Tin
        If eee = 13.5 Then
            Tin = 280
        End If
        If eee = 14.5 Then
            Tin = 300
        End If
    End If
    
    If Cells(8, 12) = "Y" Then
        '   hambient
        If eee = 10.5 Then
            hamb = 0.036
        End If
        If eee = 11.5 Then
            hamb = 0.0036
        End If
    End If
        
    If Cells(9, 12) = "Y" Then
        '   DNI
        If eee = 12.5 Then
            Iraddrop = 0.2
        End If
        If eee = 13.5 Then
            Iraddrop = 0
        End If
    End If

End Sub
'
'
Sub Process()

    Irad = Cells(1, 5)

    '   Assign Disturbances
    Tdrift = (1 - Tlambda) * Tdrift + Tlambda * Tsigmad * Sqr(-2 * Log(1 - Rnd)) * Sin(2 * 3.14159 * Rnd)
    Tin1 = Tin + Tdrift
    Iraddrift = (1 - Iradlambda) * Iraddrift + Iradlambda * Iradsigmad * Sqr(-2 * Log(1 - Rnd)) * Sin(2 * 3.14159 * Rnd)
    Irad1 = Irad + Iraddrift - Iraddrop
    For LineN = 1 To 3
        adrift(LineN) = (1 - alambda) * adrift(LineN) + alambda * asigmad * Sqr(-2 * Log(1 - Rnd)) * Sin(2 * 3.14159 * Rnd)
        flowa1(LineN) = Flowa + adrift(LineN)
        Edrift(LineN) = (1 - Elambda) * Edrift(LineN) + Elambda * Esigmad * Sqr(-2 * Log(1 - Rnd)) * Sin(2 * 3.14159 * Rnd)
        eff1(LineN) = eff + Edrift(LineN) - effdrop(LineN)
    Next LineN
    
    '   Calculate pump speed
    spumps = (1 - Exp(-dt / pumptau)) * spumpstarg + (Exp(-dt / pumptau)) * spumps     'lag to x

    '   Calculate Valve stem positions
    For Valvei = 1 To 3
        valvex(Valvei) = (1 - Exp(-dt / valvetau)) * valvextarg(Valvei) + (Exp(-dt / valvetau)) * valvex(Valvei) 'lag to x
        If valvex(Valvei) > 1 Then valvex(Valvei) = 1
        If valvex(Valvei) < 0.1 Then valvex(Valvei) = 0.1
    Next Valvei

    '   Flow rate through the pump affects pump dP, but pump dP affects flow rates through the lines and the rest of the system
    '   So, pump and valve responses are interactive.
    '   For simplicity and effectiveness, I use successive substitution (with no tempering) to determine flow rates
    '   Pump and valve are operating at Tin.
    Ftotalold = Ftotal
    Mdottotalold = Mdottotal
    For SucSubN = 1 To 10  'fewer iterations may be plenty
        '   Pump model
        sref = 2970 'rpm
        speed = spumps * sref
        Fmaxref = (224.6293 / 3600) 'm3/s
        hmaxref = 128 * dens * 9.807 / 1 / 1000 'kPa
        Fmax = Fmaxref * (speed / sref) ^ 1
        hmax = hmaxref * (speed / sref) ^ 2
        If Ftotal > Fmax Then Ftotal = Fmax
        dPpump = hmax * (1 - (Ftotal / Fmax) ^ 4.346734)      'kPa, one pump, three collection lines
        '   Boiler and Header System model
        dPSys = Flowb * Ftotal ^ 1.9
        If dPSys > dPpump Then dPSys = 0.95 * dPpump     'override to precent sqr of "-"
        '   new collection line flow rates
        For Valvei = 1 To 3
            fofx = valveR ^ (valvex(Valvei) - 1)                        'valve characteristic
            Fnew = Cv * fofx * Sqr(dPpump / (G * 1 + (dPSys / F(Valvei) ^ 2 + flowa1(Valvei) / F(Valvei) ^ 0.1) * (Cv * fofx) ^ 2)) 'flow rate m^3 per sec
            F(Valvei) = 1 * Fnew + 0 * F(Valvei) 'No tempering
        Next Valvei
        '   Calculate Ftotal
        Ftotal = 0
        For Valvei = 1 To 3
            Ftotal = Ftotal + F(Valvei)   'flow rate m^3 per sec
        Next Valvei
        If Abs(Ftotalold - Ftotal) < 0.0001 * Ftotal Then Exit For
        Ftotalold = Ftotal
    Next SucSubN
    
    For Valvei = 1 To 3
        Mdot(Valvei) = dens * F(Valvei)
    Next Valvei
    Mdottotal = dens * Ftotal
    
    
    '   Thermal model to determine oil temperature
    '   Tp is pipe T before time step
    '   Tb is fluid T before time step
    '   Ta is fluid T after time step
    '   Since flow rate in the pipe depends on density, which changes with T along the pipe, but since Mdot is uniform along
    '       the pipe, I use Mdot(LineN) / rho(Tb(LineN, k)) instead of F(LineN).
    
    ProcessF = 3.14159 * R ^ 2 * dz
    For LineN = 1 To 3
        ProcessD = Irad1 * MirrorWidth * eff1(LineN) / (3.14159 * R)
        hin = hinside(Tb(LineN, 1), LineN)
        PipeT(LineN, 1) = pipeTlambda * ((ProcessD + hin * Tb(LineN, 1) + hamb * Tamb) / (hin + hamb)) + (1 - pipeTlambda) * PipeT(LineN, 1) 'Pipe T
        densxCp = rhocp(Tb(LineN, 1))
        ProcessC = Dispersion / (densxCp * dz ^ 2)                           'Page 122
        ProcessE = R * densxCp
        Ta(LineN, 1) = Tb(LineN, 1) + dt * ((hin / ProcessE) * (PipeT(LineN, 1) - Tb(LineN, 1)) - (Mdot(LineN) / rho(Tb(LineN, 1)) / ProcessF) * (Tb(LineN, 1) - Tin1) + ProcessC * (Tb(LineN, 2) - 2 * Tb(LineN, 1) + Tin))  'entrance section
        For k = 2 To N - 1
            hin = hinside(Tb(LineN, k), LineN)
            PipeT(LineN, k) = pipeTlambda * ((ProcessD + hin * Tb(LineN, k) + hamb * Tamb) / (hin + hamb)) + (1 - pipeTlambda) * PipeT(LineN, k)
            densxCp = rhocp(Tb(LineN, k))
            ProcessC = Dispersion / (densxCp * dz)                           'Page 122
            ProcessE = R * densxCp
            If method = "B" Then    '   Backward
                Ta(LineN, k) = Tb(LineN, k) + dt * ((hin / ProcessE) * (PipeT(LineN, k) - Tb(LineN, k)) - (Mdot(LineN) / rho(Tb(LineN, k)) / ProcessF) * (Tb(LineN, k) - Tb(LineN, k - 1)) + ProcessC * (Tb(LineN, k + 1) - 2 * Tb(LineN, k) + Tb(LineN, k - 1)))
            Else                    '   Forward
                Ta(LineN, k) = Tb(LineN, k) + dt * ((hin / ProcessE) * (PipeT(LineN, k) - Tb(LineN, k)) - (Mdot(LineN) / rho(Tb(LineN, k)) / ProcessF) * (Tb(LineN, k + 1) - Tb(LineN, k - 1)) / 2 + ProcessC * (Tb(LineN, k + 1) - 2 * Tb(LineN, k) + Tb(LineN, k - 1)))
            End If
        Next k
        hin = hinside(Tb(LineN, N), LineN)
        PipeT(LineN, N) = pipeTlambda * ((ProcessD + hin * Tb(LineN, N) + hamb * Tamb) / (hin + hamb)) + (1 - pipeTlambda) * PipeT(LineN, N)
        densxCp = rhocp(Tb(LineN, N))
        ProcessC = Dispersion / (densxCp * dz)                           'Page 122
        ProcessE = R * densxCp
        Ta(LineN, N) = Tb(LineN, N) + dt * ((hin / ProcessE) * (PipeT(LineN, N) - Tb(LineN, N)) - (Mdot(LineN) / rho(Tb(LineN, N)) / ProcessF) * (Tb(LineN, N) - Tb(LineN, N - 1)) + ProcessC * (-Tb(LineN, N) + Tb(LineN, N - 1)))  'Exit section
        
        For k = 1 To N
            Tb(LineN, k) = Ta(LineN, k) 'update Tbefore with Tafter
        Next k
    Next LineN
    Tmixed = (Ta(1, N) * F(1) + Ta(2, N) * F(2) + Ta(3, N) * F(3)) / (F(1) + F(2) + F(3))

End Sub
'
'
Sub Initialize()

    Range("A14:CI3000").Select
    Selection.ClearContents
    Range("K5").Select
    
    Randomize

    method = Cells(2, 21)
    

    valveR = 50
    Cv = 10 / 3600              'to convert m3/hr to m3/sec
    Flowa = 5000000             'for a single collection line, dP=flowa*F^1.9, kPa from m3/sec
    Flowb = 0.5 * (4 / 9) * Flowa 'collection lines with equal F collectively going through the boiler and circulating system, dP=b*(3F)^2, flowb=9*b
    valvetau = 2   'sec
    
    pumptau = 2     'sec
    
    iout = 0
    simtime = 0
    EvalCount = 0
    HighTViol = 0
    LowTViol = 0
    
    N = Cells(2, 9)
    If Cells(6, 9) = "N" Then   'Initiaize here
        For LineN = 1 To 3
            Mdot(LineN) = 5.63 / 3    'kg/s    Is this one line or all three?
            F(LineN) = Mdot(LineN) / rho(300)
            For k = 1 To N
                Tb(LineN, k) = 300 + 95 * k / N        'linearly rising
                Ta(LineN, k) = 300 + 95 * k / N
                PipeT(LineN, k) = 354 + 95 * k / N  'pipe is 40 C higher than fluid
            Next k
            valvextarg(LineN) = 0.9
            valvex(LineN) = valvextarg(LineN)
            valvexm(LineN) = valvextarg(LineN)
            adrift(LineN) = 0
            Edrift(LineN) = 0
            GMCbias(LineN) = 0
            Iterm(LineN) = 0
            Tbias(LineN) = 0
            bias(LineN) = 0
            effdrop(LineN) = 0
            Fpmm(LineN) = 0
            epsilonest(LineN) = eff
            SPCV(LineN) = 0
            SPCXOLD(LineN) = 0
            CUSUM(LineN) = 0
            SPCN(LineN) = 0
        Next LineN
        TRIGGER = Cells(7, 2)
        spumpstarg = Cells(10, 12)
        spumps = spumpstarg
        pumpintegral = spumpstarg
        Mdottotal = Mdot(1) + Mdot(2) + Mdot(3)
        Ftotal = F(1) + F(2) + F(3)
    End If
    
    Irad = Cells(1, 5)
    Irad1 = Irad
    Iraddrop = 0
    MirrorWidth = Cells(2, 5)
    R = Cells(3, 5)
    L = Cells(4, 5)
    dens = Cells(5, 5)
    G = dens / 1000
    Cp = Cells(6, 5)
    Tamb = Cells(7, 5)
    hin = Cells(12, 5)
    hamb = Cells(10, 5)
    
    Tin = Cells(5, 9)
    T1SP = Cells(2, 12)
    For LineN = 1 To 3
        T2SP(LineN) = Tin + (T1SP - Tin) / 2
        T2model(LineN) = T2SP(LineN)
    Next LineN
    
    Fbase = F(1)
    eff = Cells(9, 5)
    effbase = eff
    For LineN = 1 To 3
        eff1(LineN) = eff
        epsilonest(LineN) = eff
    Next LineN
    effold = eff

    Dispersion = Cells(11, 5)
    N = Cells(2, 9)
    dz = Cells(1, 9)
    If method = "C" Then  'central difference
        dt = 0.1 * (dz * 3.14159 * R ^ 2) / 0.006      '0.006 is a nominal high F for the collection line
    Else                'backward difference
        dt = 0.2 * (dz * 3.14159 * R ^ 2) / 0.006
    End If
    Cells(4, 9) = dt
    Iraddrift = 0
    tauIraddrift = Cells(4, 23)
    rangeIraddrift = Cells(5, 23)
    Iradlambda = 1 - Exp(-dt / tauIraddrift)
    Iradsigmad = (rangeIraddrift / 5) * Sqr((2 - Iradlambda) / Iradlambda)
        
    Tdrift = 0
    tauTdrift = Cells(4, 21)
    rangeTdrift = Cells(5, 21)
    Tlambda = 1 - Exp(-dt / tauTdrift)
    Tsigmad = (rangeTdrift / 5) * Sqr((2 - Tlambda) / Tlambda)
    
    For LineN = 1 To 3
        adrift(LineN) = 0
    Next LineN
    tauadrift = Cells(4, 25)
    rangeadrift = Cells(5, 25)
    alambda = 1 - Exp(-dt / tauadrift)
    asigmad = (rangeadrift / 5) * Sqr((2 - alambda) / alambda)
    
    For LineN = 1 To 3
        Edrift(LineN) = 0
    Next LineN
    tauEdrift = Cells(4, 19)
    rangeEdrift = Cells(5, 19)
    Elambda = 1 - Exp(-dt / tauEdrift)
    Esigmad = (rangeEdrift / 5) * Sqr((2 - Elambda) / Elambda)
    
    Fmeasnoise = Cells(5, 28)
    noiseFiltTau = Cells(7, 2)
    cinterval = Cells(1, 12)
    If noiseFiltTau > 0 Then
        noiselambda = 1 - Exp(-cinterval / noiseFiltTau)
    Else
        noiselambda = 1
    End If
    
    pipeTtimeconstant = 10          'average over F range Page 1
    If pipeTtimeconstant > 0 Then
        pipeTlambda = 1 - Exp(-dt / pipeTtimeconstant)
    Else
        pipeTlambda = 1
    End If
    
    FlowaFiltTau = Cells(3, 2)
    If FlowaFiltTau > 0 Then
        Flowalambda = 1 - Exp(-cinterval / FlowaFiltTau)
    Else
        Flowalambda = 1
    End If
    
    FpmmFiltTau = Cells(2, 2)
    If FpmmFiltTau > 0 Then
        Fpmmlambda = 1 - Exp(-cinterval / FpmmFiltTau)
    Else
        Fpmmlambda = 1
    End If
    
    LineN = Cells(1, 21)
    Cells(14, 3) = 8 + simtime / 3600
    Cells(14, 4) = Tb(LineN, 1)
    For kk = 1 To 10
        Cells(14, kk + 4) = Tb(LineN, kk * Round(N / 10, 0))
    Next kk
    
    Cells(14, 19) = 8 + simtime / 3600
    Cells(14, 20) = eff
    
    Cells(14, 22) = 8 + simtime / 3600
    
    Velement = dz * 3.14159 * R ^ 2

    cinterval = 0
    controlcount = 0
    
    Told = Ta(LineN, N)
    Fold = F(LineN)
    effmeasold = eff
    
    tauw = Cells(3, 12)
    
    For LineN = 1 To 3
        ISE1(LineN) = 0
        ISE2(LineN) = 0
    Next LineN
    
    GMCGain = Cells(6, 12)
    
    Cells(13, 4) = 1
    For kk = 1 To 10
        Cells(13, kk + 4) = kk * N / 10
    Next kk
    
    spumps = Cells(10, 12)
    spumpsold = spumps
    
    T1PIGain = Cells(10, 9)
    T1PITau = Cells(11, 9)
    
    PumpPIGain = Cells(9, 17)
    PumpPITau = Cells(10, 17)
    
    MBCtauw = Cells(6, 2)
    
    PEnergy = 0
    
    minRe = 100000000
    maxRe = 0
    
    minTheta = 100000000
    maxTheta = 0
    
    interval_count = Int(700 + 50 * Rnd())            'randomize the output interval to prevent aliasing
    subinterval_count = 0
    
    Tmixed = 395
    PumpTravel = 0
    ValveTravel = 0
    TotalEnergy = 0
    
End Sub
'
'
Sub Output()
'
'    If i = interval_count * Int(i / interval_count) Then
        iout = iout + 1
        
'        If method = "C" Then
'            interval_count = Int(700 + 50 * Rnd())            'randomize the output interval to prevent aliasing
'        Else
'            interval_count = Int(25 + 50 * Rnd())
'        End If
        
        Cells(4, 2) = " " & itrial & " , " & iout
        
        Cells(5, 15) = minRe
        Cells(6, 15) = maxRe
        
        Cells(10, 12) = spumpstarg
        
        Cells(1, 5) = DNI

        LineN = Cells(1, 21)

        Cells(iout + 14, 3) = 8 + simtime / 3600
        Cells(iout + 14, 2) = T2SP(LineN)
        Cells(iout + 14, 1) = midTerror(LineN)
        Cells(iout + 14, 4) = Ta(LineN, 1)
        Cells(iout + 14, 73) = PipeT(LineN, 1)
        For kk = 1 To 10
            kkk = kk * Round(N / 10, 0)
            Cells(iout + 14, kk + 4) = Ta(LineN, kkk)
            Cells(iout + 14, kk + 73) = PipeT(LineN, kkk)
        Next kk
        
        Cells(iout + 14, 15) = Tmixed
        
        Cells(iout + 14, 19) = 8 + simtime / 3600
        Cells(iout + 14, 20) = eff1(LineN)
        Cells(iout + 14, 21) = epsilonest(LineN)
        
        Cells(iout + 14, 22) = 8 + simtime / 3600
        Cells(iout + 14, 23) = F(LineN)
        Cells(9, 23) = F(LineN)
        Cells(iout + 14, 24) = Tin1
        
        Cells(iout + 14, 26) = 8 + simtime / 3600
        Cells(iout + 14, 27) = Irad1
        Cells(iout + 14, 28) = Iradmeas
        Cells(iout + 14, 29) = Fdesired(LineN)
        Cells(iout + 14, 30) = Fpmm(LineN)
        
        Theta = (3.14159 * R ^ 2) * L / F(LineN)
        Cells(1, 15) = Theta
        Cells(2, 15) = simtime
        
        Cells(4, 12) = F(LineN)
        Cells(5, 12) = eff1(LineN)
        
        nISE1 = ISE1(LineN) / EvalCount
        Cells(11, 12) = 2.5 * Sqr(nISE1)
        nISE2 = ISE2(LineN) / EvalCount
        Cells(12, 12) = 2.5 * Sqr(nISE2)
        
'        nISE1Total = (ISE1(1) + ISE1(2) + ISE1(3)) / (3 * EvalCount)
'        Cells(11, 2) = Sqr(nISE1Total)
        
        Cells(iout + 14, 31) = flowa1(LineN)
        Cells(iout + 14, 32) = flowaest(LineN)
        
        Cells(iout + 14, 33) = 8 + simtime / 3600
            fofx = valveR ^ (valvex(LineN) - 1)
            linedp(LineN) = dPpump - dPSys - (F(LineN) / (Cv * fofx)) ^ 2
        Cells(iout + 14, 34) = linedp(LineN)
        Cells(iout + 14, 35) = valvex(LineN)
        fofx = valveR ^ (valvex(LineN) - 1)
        Cells(iout + 14, 36) = G * 1 * (F(LineN) / Cv / fofx) ^ 2        'valve dP
        Cells(iout + 14, 37) = flowa1(LineN) * (F(LineN)) ^ 2                          'line dP
        Cells(iout + 14, 38) = dPLmeas(LineN)                         'line dP measured
        Cells(iout + 14, 39) = Flowb * (Ftotal) ^ 2                          'boiler and system dP
        
        Cells(iout + 14, 40) = 8 + simtime / 3600
        Cells(iout + 14, 41) = T2model(LineN)
        Cells(iout + 14, 42) = Ta(LineN, N)
        Cells(iout + 14, 43) = spumps
        
        Cells(iout + 14, 44) = 8 + simtime / 3600
        Cells(iout + 14, 45) = valvex(LineN)
        Cells(iout + 14, 46) = valvextarg(LineN)
        Cells(iout + 14, 47) = fofx
        Cells(iout + 14, 48) = fofxm
        Cells(iout + 14, 49) = F(LineN)
        Cells(iout + 14, 50) = Fm(LineN)
        
        Cells(iout + 14, 51) = hinside(Ta(LineN, 1), LineN)
        Cells(iout + 14, 52) = hinside(Ta(LineN, N), LineN)
        Cells(iout + 14, 53) = Fmeas(LineN)
        Cells(iout + 14, 54) = Fmeasfilt(1)
        Cells(iout + 14, 55) = Fmeasfilt(2)
        Cells(iout + 14, 56) = Fmeasfilt(3)
        Cells(iout + 14, 57) = Ftotal
        Cells(iout + 14, 58) = flowa1(1)
        Cells(iout + 14, 59) = flowa1(2)
        Cells(iout + 14, 60) = flowa1(3)
        Cells(iout + 14, 61) = eff1(1)
        Cells(iout + 14, 62) = eff1(2)
        Cells(iout + 14, 63) = eff1(3)
        Cells(iout + 14, 64) = valvex(1)
        Cells(iout + 14, 65) = valvex(2)
        Cells(iout + 14, 66) = valvex(3)
        Cells(iout + 14, 67) = Tb(1, N)
        Cells(iout + 14, 68) = Tb(2, N)
        Cells(iout + 14, 69) = Tb(3, N)
        Cells(iout + 14, 70) = Fdesired(1)
        Cells(iout + 14, 71) = Fdesired(2)
        Cells(iout + 14, 72) = Fdesired(3)
        
        Cells(10, 2) = PEnergy
        
        Cells(1, 24) = HighTViol * cinterval
        Cells(1, 27) = LowTViol * cinterval
        Cells(2, 24) = PumpTravel
        Cells(2, 27) = ValveTravel
        Cells(7, 22) = TotalEnergy
        
        Theta = Cells(1, 17)
        If Theta > maxTheta Then maxTheta = Theta
        If Theta < minTheta Then minTheta = Theta
        Cells(10, 21) = maxTheta
        Cells(11, 21) = minTheta
        
        subinterval_count = subinterval_count + 1
        If subinterval_count = 5 * Int(subinterval_count / 5) Then
            Cells(Int(subinterval_count / 5) + 14, 85) = 8 + simtime / 3600
            Cells(Int(subinterval_count / 5) + 14, 86) = Ta(LineN, N)
            Cells(Int(subinterval_count / 5) + 14, 87) = Tmixed
        End If
        
        Calculate
'        Application.ScreenUpdating = True
        Ostarttime = Timer
        Do Until Timer > Ostarttime + 0.01
            DoEvents
        Loop
'        Application.ScreenUpdating = False
        
'    End If
    
End Sub
'
'
Sub Tdistribution()
    
    ActiveWindow.SmallScroll Down:=96
    Range("D130:N130").Select
    Selection.Copy
    
    Range("Q14").Select
    Selection.PasteSpecial Paste:=xlPasteAll, Operation:=xlNone, SkipBlanks:= _
       False, Transpose:=True
    Range("K6").Select
    
    Cells(14, 16) = 1
    For jj = 1 To 10
        Cells(jj + 14, 16) = 50 * jj
    Next jj

End Sub
'
'
Sub Evaluate()

    EvalCount = EvalCount + 1
    
    Nmid = Int(N / 2)
    For LineN = 1 To 3
        ISE2(LineN) = ISE2(LineN) + (T2SP(LineN) - Ta(LineN, Nmid)) ^ 2         'mid-line T deviation from Setpont
        ISE1(LineN) = ISE1(LineN) + (T1SP - Ta(LineN, N)) ^ 2                   'exit Line T deviation from Setpoint
        If Ta(LineN, N) > 400 Then HighTViol = HighTViol + (Ta(LineN, N) - 400) ^ 2     'penalty for too high a T
    Next LineN
    If Tmixed < 390 Then LowTViol = LowTViol + (390 - Tmixed)                           'penalty for too low a mixed T
    PumpTravel = PumpTravel + Abs(spumps - spumpsold)
    spumpsold = spumps
    ValveTravel = ValveTravel + Abs(valvex(1) - valvexold(1)) + Abs(valvex(2) - valvexold(2)) + Abs(valvex(3) - valvexold(3))
    valvexold(1) = valvex(1)
    valvexold(2) = valvex(2)
    valvexold(3) = valvex(3)
    
    PEnergy = PEnergy + cinterval * Ftotal * dPpump / 3600      'kiloWatt-hr
    TotalEnergy = TotalEnergy + cinterval * Ftotal * rhocp((Tmixed + Tin) / 2) * (Tmixed - Tin) / 3600 'kiloWatt-hr


End Sub
'
'
Function hinside(localT, LineN)
    'localT is Centigrade and needs to be converted to Kelvin
    'Re=(4 F dens)/(Pi D mu gc)
    'F is m3/s
    'Pr = (Cp Mu gc)/k
    'Dittus-Boelter Nu=hD/k = 0.023 * Re^.8 * Pr^.4
    
    If localT < 250 Then localT = 250
    If localT > 500 Then localT = 500
    
    localTK = localT + 273.15
    
    fluid_dens = 960.73 + 0.11489 * localTK - 0.001082 * localTK ^ 2            'kg/m3
    fluid_Cp = (1108.027 + 1.70714 * localTK) / 1000                            'kJ/(kg*K)
    fluid_k = (0.19091 - 0.0001894 * localTK) / 1000                            'kW/(m*K)
    fluid_visc = (0.0000394059 * Exp(1636.999 / localTK) - 0.0002115)     'Pa*s
    
    gc = 1      '(kg m)/(N s2)
    D = 2 * R
    
    Re = 4 * F(LineN) * fluid_dens / (3.14159 * D * fluid_visc * gc)
    If Re > maxRe Then maxRe = Re
    If Re < minRe Then minRe = Re
    Pr = fluid_Cp * fluid_visc * gc / fluid_k
    hinside = (fluid_k / D) * 0.023 * Re ^ 0.8 * Pr ^ 0.4

End Function
'
'
Function rhocp(localT)
    'localT is Centigrade and needs to be converted to Kelvin
    
    If localT < 250 Then localT = 250
    If localT > 500 Then localT = 500
    
    localTK = localT + 273.15
    
    fluid_dens = 960.73 + 0.11489 * localTK - 0.001082 * localTK ^ 2  'kg/m3
    fluid_Cp = (1108.027 + 1.70714 * localTK) / 1000                  'kJ/(kg*K)
    
    rhocp = fluid_dens * fluid_Cp

End Function
'
'
Function rho(localT)
    'localT is Centigrade and needs to be converted to Kelvin
    
    If localT < 250 Then localT = 250
    If localT > 500 Then localT = 500
    
    localTK = localT + 273.15
    
    rho = 960.73 + 0.11489 * localTK - 0.001082 * localTK ^ 2  'kg/m3
    
End Function
